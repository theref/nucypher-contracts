// SPDX-License-Identifier: AGPL-3.0-or-later

pragma solidity ^0.8.0;

import "@openzeppelin/contracts/access/Ownable.sol";

/**
* @title Verifier
* @notice Verification layer for DKG-TDec
*/
contract Verifier is Ownable {
    event StartAggregationRound(uint32 indexed ritualId);
    event EndVerification(uint32 indexed ritualId, address indexed initiator, VerificationState status);

    // Node
    event TranscriptCommitted(uint32 indexed ritualId, address indexed node, bytes32 transcriptDigest);
    event AggregationCommitted(uint32 indexed ritualId, address indexed node, bytes32 aggregatedTranscriptDigest);

    
    
    // Admin
    event TimeoutChanged(uint32 oldTimeout, uint32 newTimeout);

    enum VerificationState {
        NON_INITIATED,
        AWAITING_TRANSCRIPTS,
        AWAITING_AGGREGATIONS,
        TIMEOUT,
        INVALID,
        FINALIZED
    }

    uint256 public constant PUBLIC_KEY_SIZE = 48;

    struct Participant {
        address node;
        bool aggregated;
        bytes32 transcriptCommitment;
    }

    // TODO: Optimize layout
    struct Ritual {
        uint32 id;  // TODO: Redundant? ID is index of rituals array
        address initiator;
        uint32 dkgSize;
        uint32 initTimestamp;
        uint32 totalTranscripts;
        uint32 totalAggregations;
        bytes1[PUBLIC_KEY_SIZE] publicKey;
        bytes32 aggregatedTranscriptHash;
        bool aggregationMismatch;
        bytes aggregatedTranscript;
        Participant[] participant;
    }

    Ritual[] public rituals;

    uint32 public timeout;

    address public bulletinBoard;
    address public coordinator;

    function getVerificationState(uint256 ritualId) external view returns (VerificationState){
        // TODO: restrict to ritualID < rituals.length?
        return getVerificationState(rituals[ritualId]);
    }

    function getVerificationState(Ritual storage ritual) internal view returns (VerificationState){
        uint32 t0 = ritual.initTimestamp;
        uint32 deadline = t0 + timeout;
        if(t0 == 0){
            return VerificationState.NON_INITIATED;
        } else if (ritual.publicKey[0] != 0x0){ // TODO: Improve check
            return VerificationState.FINALIZED;
        } else if (ritual.aggregationMismatch){
            return VerificationState.INVALID;
        } else if (block.timestamp > deadline){
            return VerificationState.TIMEOUT;
        } else if (ritual.totalTranscripts < ritual.dkgSize) {
            return VerificationState.AWAITING_TRANSCRIPTS;
        } else if (ritual.totalAggregations < ritual.dkgSize) {
            return VerificationState.AWAITING_AGGREGATIONS;
        } else {
            // TODO: Is it possible to reach this state?
            //   - No public key
            //   - All transcripts and all aggregations
            //   - Still within the deadline
        }
    }

    function commitToTranscript(uint32 ritualId, uint256 nodeIndex, bytes32 transcriptCommitment) external {
        Ritual storage ritual = rituals[ritualId];
        require(
            getVerificationState(ritual) == VerificationState.AWAITING_TRANSCRIPTS,
            "Not waiting for transcripts"
        );
        Participant storage participant = ritual.participant[nodeIndex];
        require(
            participant.node == msg.sender,
            "Node not part of ritual"
        );
        require(
            participant.transcriptCommitment == bytes32(0),
            "Node already posted transcript"
        );

        // Nodes commit to their transcript
        participant.transcriptCommitment = transcriptCommitment;
        emit TranscriptCommitted(ritualId, msg.sender, transcriptCommitment);
        ritual.totalTranscripts++;

        // end round
        if (ritual.totalTranscripts == ritual.dkgSize){
            emit StartAggregationRound(ritualId);
        }
    }

    function commitToAggregation(uint32 ritualId, uint256 nodeIndex, bytes32 aggregatedTranscriptCommittment) external {
        Ritual storage ritual = rituals[ritualId];
        require(
            getVerificationState(ritual) == VerificationState.AWAITING_AGGREGATIONS,
            "Not waiting for aggregations"
        );
        Participant storage participant = ritual.participant[nodeIndex];
        require(
            participant.node == msg.sender,
            "Node not part of ritual"
        );
        require(
            !participant.aggregated,
            "Node already posted aggregation"
        );

        // nodes commit to their aggregation result
        participant.aggregated = true;
        emit AggregationCommitted(ritualId, msg.sender, aggregatedTranscriptCommittment);

        if (ritual.aggregatedTranscriptHash == bytes32(0)){
            ritual.aggregatedTranscriptHash = aggregatedTranscriptCommittment;
        } else if (ritual.aggregatedTranscriptHash != aggregatedTranscriptCommittment){
            ritual.aggregationMismatch = true;
            emit EndVerification(ritualId, ritual.initiator, VerificationState.INVALID);
            // TODO: Invalid ritual
            // TODO: Consider freeing ritual storage
            return;
        }
        ritual.totalAggregations++;
        
        // end round - Last node posting aggregation will finalize 
        if (ritual.totalAggregations == ritual.dkgSize){
            emit EndVerification(ritualId, ritual.initiator, VerificationState.FINALIZED);
            // TODO: Last node extracts public key bytes from aggregated transcript
            // and store in ritual.publicKey
            ritual.publicKey[0] = bytes1(0x42);
        }
    }


    function setTimeout(uint32 newTimeout) external onlyOwner {
        emit TimeoutChanged(timeout, newTimeout);
        timeout = newTimeout;
    }
    
}