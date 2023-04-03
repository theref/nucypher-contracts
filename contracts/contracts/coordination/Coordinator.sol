// SPDX-License-Identifier: AGPL-3.0-or-later

pragma solidity ^0.8.0;

import "@openzeppelin/contracts/access/Ownable.sol";

/**
* @title Coordinator
* @notice Coordination layer for DKG-TDec
*/
contract Coordinator is Ownable {

    // Ritual
    event StartRitual(uint32 indexed ritualId, address indexed initiator, address[] nodes);
    event StartTranscriptRound(uint32 indexed ritualId, address verifier);
    // TODO: Do we want the public key here? If so, we want 2 events or do we reuse this event?
    event EndRitual(uint32 indexed ritualId, address indexed initiator, RitualState status);



    // Admin
    event TimeoutChanged(uint32 oldTimeout, uint32 newTimeout);
    event MaxDkgSizeChanged(uint32 oldSize, uint32 newSize);
    event VerifierChanged(address oldVerifier, address newVerifier);

    enum RitualState {
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
    uint32 public maxDkgSize;

    address public verifier;

    constructor(uint32 _timeout, uint32 _maxDkgSize) {
        timeout = _timeout;
        maxDkgSize = _maxDkgSize;
    }

    function getRitualState(uint256 ritualId) external view returns (RitualState){
        // TODO: restrict to ritualID < rituals.length?
        return getRitualState(rituals[ritualId]);
    }

    function getRitualState(Ritual storage ritual) internal view returns (RitualState){
        uint32 t0 = ritual.initTimestamp;
        uint32 deadline = t0 + timeout;
        if(t0 == 0){
            return RitualState.NON_INITIATED;
        } else if (ritual.publicKey[0] != 0x0){ // TODO: Improve check
            return RitualState.FINALIZED;
        } else if (ritual.aggregationMismatch){
            return RitualState.INVALID;
        } else if (block.timestamp > deadline){
            return RitualState.TIMEOUT;
        } else if (ritual.totalTranscripts < ritual.dkgSize) {
            return RitualState.AWAITING_TRANSCRIPTS;
        } else if (ritual.totalAggregations < ritual.dkgSize) {
            return RitualState.AWAITING_AGGREGATIONS;
        } else {
            // TODO: Is it possible to reach this state?
            //   - No public key
            //   - All transcripts and all aggregations
            //   - Still within the deadline
        }
    }
    

    function setTimeout(uint32 newTimeout) external onlyOwner {
        emit TimeoutChanged(timeout, newTimeout);
        timeout = newTimeout;
    }

    function setMaxDkgSize(uint32 newSize) external onlyOwner {
        emit MaxDkgSizeChanged(maxDkgSize, newSize);
        maxDkgSize = newSize;
    }

    function numberOfRituals() external view returns(uint256) {
        return rituals.length;
    }

    function getParticipants(uint32 ritualId) external view returns(Participant[] memory) {
        Ritual storage ritual = rituals[ritualId];
        return ritual.participant;
    }

    function initiateRitual(address[] calldata nodes) external returns (uint32) {
        // TODO: Validate service fees, expiration dates, threshold
        require(nodes.length <= maxDkgSize, "Invalid number of nodes");

        uint32 id = uint32(rituals.length);
        Ritual storage ritual = rituals.push();
        ritual.id = id;  // TODO: Possibly redundant
        ritual.initiator = msg.sender;  // TODO: Consider sponsor model
        ritual.dkgSize = uint32(nodes.length);
        ritual.initTimestamp = uint32(block.timestamp);

        address previousNode = address(0);
        for(uint256 i=0; i < nodes.length; i++){
            Participant storage newParticipant = ritual.participant.push();
            address currentNode = nodes[i];
            newParticipant.node = currentNode;
            require(previousNode < currentNode, "Nodes must be sorted");
            previousNode = currentNode;
            // TODO: Check nodes are eligible (staking, etc)
        }
        // TODO: Compute cohort fingerprint as hash(nodes)

        emit StartRitual(id, msg.sender, nodes);
        emit StartTranscriptRound(id, verifier);
        return ritual.id;
    }
}
