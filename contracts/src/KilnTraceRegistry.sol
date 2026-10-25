// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import {AccessControl} from "@openzeppelin/contracts/access/AccessControl.sol";
import {EIP712} from "@openzeppelin/contracts/utils/cryptography/EIP712.sol";
import {ECDSA} from "@openzeppelin/contracts/utils/cryptography/ECDSA.sol";
import {MerkleProof} from "@openzeppelin/contracts/utils/cryptography/MerkleProof.sol";

/// @title KilnTrace evidence registry
/// @notice Stores one Merkle root per pipeline run (batch), verifies kiln records against it,
///         accepts EIP-712 signed field checks relayed by a backend, and manages disputes.
contract KilnTraceRegistry is AccessControl, EIP712 {
    bytes32 public constant PUBLISHER_ROLE = keccak256("PUBLISHER_ROLE");
    bytes32 public constant REVIEWER_ROLE = keccak256("REVIEWER_ROLE");

    enum Verdict { Unknown, ConfirmNonZigzag, ConfirmZigzag, NotAKiln, ActiveDuringBan, Closed }
    enum DisputeStatus { None, Open, Upheld, Rejected }

    struct Batch {
        bytes32 merkleRoot; bytes32 modelSha256; bytes20 codeCommit;
        uint64 sceneDate; uint64 committedAt; uint32 recordCount;
        address publisher; string manifestCID;
    }
    struct FieldCheck {
        bytes32 kilnId; uint256 batchId; Verdict verdict;
        address reporter; uint64 observedAt; string evidenceCID;
    }
    struct Dispute {
        bytes32 kilnId; uint256 batchId; address opener;
        DisputeStatus status; string evidenceCID; string resolutionCID;
    }

    bytes32 public constant FIELD_CHECK_TYPEHASH = keccak256(
        "FieldCheck(bytes32 kilnId,uint256 batchId,uint8 verdict,uint64 observedAt,string evidenceCID,uint256 nonce)");

    Batch[] private _batches;
    FieldCheck[] private _checks;
    Dispute[] private _disputes;
    mapping(address => uint256) public nonces;

    event BatchCommitted(uint256 indexed batchId, bytes32 merkleRoot, string manifestCID,
                         bytes32 modelSha256, uint64 sceneDate, uint32 recordCount);
    event FieldCheckSubmitted(uint256 indexed checkId, bytes32 indexed kilnId, uint256 indexed batchId,
                              address reporter, Verdict verdict, string evidenceCID);
    event DisputeOpened(uint256 indexed disputeId, bytes32 indexed kilnId, uint256 indexed batchId,
                        address opener, string evidenceCID);
    event DisputeResolved(uint256 indexed disputeId, DisputeStatus status, string resolutionCID);

    error UnknownBatch(); error BadSignature(); error NotOpen(); error EmptyRoot(); error UnknownDispute();

    constructor(address admin) EIP712("KilnTrace", "1") { _grantRole(DEFAULT_ADMIN_ROLE, admin); }

    function commitBatch(bytes32 root, string calldata manifestCID, bytes32 modelSha256,
                         bytes20 codeCommit, uint64 sceneDate, uint32 recordCount)
        external onlyRole(PUBLISHER_ROLE) returns (uint256 batchId)
    {
        if (root == bytes32(0)) revert EmptyRoot();
        batchId = _batches.length;
        _batches.push(Batch(root, modelSha256, codeCommit, sceneDate, uint64(block.timestamp),
                            recordCount, msg.sender, manifestCID));
        emit BatchCommitted(batchId, root, manifestCID, modelSha256, sceneDate, recordCount);
    }

    function verifyRecord(uint256 batchId, bytes32 kilnId, bytes32 recordHash, bytes32[] calldata proof)
        external view returns (bool)
    {
        if (batchId >= _batches.length) revert UnknownBatch();
        bytes32 leaf = keccak256(bytes.concat(keccak256(abi.encode(kilnId, recordHash))));
        return MerkleProof.verifyCalldata(proof, _batches[batchId].merkleRoot, leaf);
    }

    /// Reporter signs off-chain (EIP-712); anyone (our relayer) submits and pays gas.
    function submitFieldCheck(bytes32 kilnId, uint256 batchId, Verdict verdict, uint64 observedAt,
                              string calldata evidenceCID, address reporter, bytes calldata signature)
        external returns (uint256 checkId)
    {
        if (batchId >= _batches.length) revert UnknownBatch();
        bytes32 structHash = keccak256(abi.encode(FIELD_CHECK_TYPEHASH, kilnId, batchId, uint8(verdict),
                                                  observedAt, keccak256(bytes(evidenceCID)), nonces[reporter]));
        if (ECDSA.recover(_hashTypedDataV4(structHash), signature) != reporter) revert BadSignature();
        nonces[reporter]++;
        checkId = _checks.length;
        _checks.push(FieldCheck(kilnId, batchId, verdict, reporter, observedAt, evidenceCID));
        emit FieldCheckSubmitted(checkId, kilnId, batchId, reporter, verdict, evidenceCID);
    }

    function openDispute(bytes32 kilnId, uint256 batchId, string calldata evidenceCID)
        external returns (uint256 disputeId)
    {
        if (batchId >= _batches.length) revert UnknownBatch();
        disputeId = _disputes.length;
        _disputes.push(Dispute(kilnId, batchId, msg.sender, DisputeStatus.Open, evidenceCID, ""));
        emit DisputeOpened(disputeId, kilnId, batchId, msg.sender, evidenceCID);
    }

    function resolveDispute(uint256 disputeId, bool upheld, string calldata resolutionCID)
        external onlyRole(REVIEWER_ROLE)
    {
        if (disputeId >= _disputes.length) revert UnknownDispute();
        Dispute storage d = _disputes[disputeId];
        if (d.status != DisputeStatus.Open) revert NotOpen();
        d.status = upheld ? DisputeStatus.Upheld : DisputeStatus.Rejected;
        d.resolutionCID = resolutionCID;
        emit DisputeResolved(disputeId, d.status, resolutionCID);
    }

    function batchCount() external view returns (uint256) { return _batches.length; }
    function getBatch(uint256 id) external view returns (Batch memory) { return _batches[id]; }
    function checkCount() external view returns (uint256) { return _checks.length; }
    function getCheck(uint256 id) external view returns (FieldCheck memory) { return _checks[id]; }
    function disputeCount() external view returns (uint256) { return _disputes.length; }
    function getDispute(uint256 id) external view returns (Dispute memory) { return _disputes[id]; }
}
