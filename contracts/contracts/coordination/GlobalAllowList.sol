// SPDX-License-Identifier: AGPL-3.0-or-later

pragma solidity ^0.8.0;

import "@openzeppelin/contracts/utils/cryptography/MessageHashUtils.sol";
import "@openzeppelin/contracts/utils/cryptography/ECDSA.sol";
import "./IEncryptionAuthorizer.sol";
import "./Coordinator.sol";

contract GlobalAllowList is IEncryptionAuthorizer {
    using MessageHashUtils for bytes32;
    using ECDSA for bytes32;

    Coordinator public immutable coordinator;

    mapping(bytes32 => bool) internal authorizations;

    mapping(uint32 => uint256) public authActions;

    event AddressAuthorizationSet(
        uint32 indexed ritualId,
        address indexed _address,
        bool isAuthorized
    );

    constructor(Coordinator _coordinator) {
        require(address(_coordinator) != address(0), "Coordinator cannot be zero address");
        require(_coordinator.numberOfRituals() >= 0, "Invalid coordinator");
        coordinator = _coordinator;
    }

    modifier canSetAuthorizations(uint32 ritualId) virtual {
        require(
            coordinator.getAuthority(ritualId) == msg.sender,
            "Only ritual authority is permitted"
        );
        _;
    }

    function lookupKey(uint32 ritualId, address encryptor) internal pure returns (bytes32) {
        return keccak256(abi.encodePacked(ritualId, encryptor));
    }

    function isAddressAuthorized(uint32 ritualId, address encryptor) public view returns (bool) {
        return authorizations[lookupKey(ritualId, encryptor)];
    }

    function _beforeIsAuthorized(
        uint32 ritualId,
        bytes memory evidence,
        bytes memory ciphertextHeader
    ) internal view virtual {}

    function isAuthorized(
        uint32 ritualId,
        bytes memory evidence,
        bytes memory ciphertextHeader
    ) external view override returns (bool) {
        _beforeIsAuthorized(ritualId, evidence, ciphertextHeader);

        bytes32 digest = keccak256(ciphertextHeader);
        address recoveredAddress = digest.toEthSignedMessageHash().recover(evidence);
        return isAddressAuthorized(ritualId, recoveredAddress);
    }

    function _beforeSetAuthorization(
        uint32 ritualId,
        address[] calldata addresses,
        bool value
    ) internal view virtual {}

    function authorize(
        uint32 ritualId,
        address[] calldata addresses
    ) external canSetAuthorizations(ritualId) {
        setAuthorizations(ritualId, addresses, true);
    }

    function deauthorize(
        uint32 ritualId,
        address[] calldata addresses
    ) external canSetAuthorizations(ritualId) {
        setAuthorizations(ritualId, addresses, false);
    }

    function setAuthorizations(uint32 ritualId, address[] calldata addresses, bool value) internal {
        require(coordinator.isRitualActive(ritualId), "Only active rituals can set authorizations");

        _beforeSetAuthorization(ritualId, addresses, value);
        for (uint256 i = 0; i < addresses.length; i++) {
            authorizations[lookupKey(ritualId, addresses[i])] = value;
            emit AddressAuthorizationSet(ritualId, addresses[i], value);
        }

        authActions[ritualId] += addresses.length;
    }
}
