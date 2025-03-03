// SPDX-License-Identifier: MIT
pragma solidity 0.8.17;

import "@openzeppelin/contracts/utils/cryptography/ECDSA.sol";
import "@account-abstraction/contracts/interfaces/IAccount.sol";
import "@account-abstraction/contracts/core/EntryPoint.sol";

/**
 * @title Threshold4337
 * @dev Implements ERC-4337 account abstraction with threshold multisig capabilities
 */
contract Threshold4337 is IAccount {
    using ECDSA for bytes32;

    // Multisig configuration
    address[] public signers;
    uint256 public immutable threshold;
    EntryPoint public immutable entryPoint;

    mapping(address => bool) public isSigner;
    mapping(bytes32 => bool) public executedOps;

    event OperationExecuted(bytes32 indexed operationHash, address indexed sender);

    /**
     * @dev Constructor for Threshold4337 contract
     * @param _signers Array of signer addresses
     * @param _threshold Minimum required number of signatures
     * @param _entryPoint Address of ERC-4337 EntryPoint contract
     */
    constructor(address[] memory _signers, uint256 _threshold, address _entryPoint) {
        require(_signers.length >= _threshold, "Threshold exceeds signers count");
        require(_threshold > 0, "Threshold must be positive");
        require(_entryPoint != address(0), "EntryPoint cannot be zero address");
        
        signers = _signers;
        threshold = _threshold;
        entryPoint = EntryPoint(_entryPoint);

        for (uint256 i = 0; i < _signers.length; i++) {
            require(_signers[i] != address(0), "Signer cannot be zero address");
            require(!isSigner[_signers[i]], "Duplicate signer");
            isSigner[_signers[i]] = true;
        }
    }

    /**
     * @dev Validates a user operation according to ERC-4337
     * @param userOp The user operation to validate
     * @param userOpHash Hash of the user operation
     * @param missingWalletFunds Amount of funds to pay to the entry point
     * @return validationData Packed validation data (see ERC-4337 spec)
     */
    function validateUserOp(
        UserOperation calldata userOp,
        bytes32 userOpHash,
        uint256 missingWalletFunds
    ) external override returns (uint256 validationData) {
        require(msg.sender == address(entryPoint), "Caller must be EntryPoint");
        require(_verifyMultisigSignature(userOpHash, userOp.signature), "Invalid multisig signature");

        // Handle funding for gas if needed
        if (missingWalletFunds > 0) {
            (bool success,) = msg.sender.call{value: missingWalletFunds}("");
            require(success, "Failed to fund wallet");
        }

        return 0; // Return 0 indicates successful validation
    }

    /**
     * @dev Executes a transaction with multisig validation
     * @param to Destination address for the transaction
     * @param value Amount of ETH to send
     * @param data Calldata for the transaction
     * @param signatures Concatenated signatures from signers
     */
    function executeTransaction(
        address to,
        uint256 value,
        bytes calldata data,
        bytes calldata signatures
    ) external {
        require(to != address(0), "Invalid destination address");
        
        bytes32 operationHash = keccak256(abi.encodePacked(to, value, data, block.number));
        require(!executedOps[operationHash], "Operation already executed");
        require(_verifyMultisigSignature(operationHash, signatures), "Invalid signatures");

        executedOps[operationHash] = true;
        
        (bool success,) = to.call{value: value}(data);
        require(success, "Transaction failed");

        emit OperationExecuted(operationHash, msg.sender);
    }

    /**
     * @dev Verifies that the signature meets the threshold requirement
     * @param operationHash Hash of the operation to verify
     * @param signature Concatenated signatures from signers
     * @return True if the signature is valid, false otherwise
     */
    function _verifyMultisigSignature(bytes32 operationHash, bytes memory signature) internal view returns (bool) {
        address[] memory recoveredSigners = _recoverSigners(operationHash, signature);
        uint256 validSignatures;

        for (uint256 i = 0; i < recoveredSigners.length; i++) {
            if (isSigner[recoveredSigners[i]]) {
                validSignatures++;
                if (validSignatures >= threshold) {
                    return true;
                }
            }
        }
        return false;
    }

    /**
     * @dev Recovers signer addresses from concatenated signatures
     * @param hash Message hash that was signed
     * @param signatures Concatenated signatures
     * @return Array of recovered signer addresses
     */
    function _recoverSigners(bytes32 hash, bytes memory signatures) internal pure returns (address[] memory) {
        require(signatures.length % 65 == 0, "Invalid signature length");
        uint256 sigCount = signatures.length / 65; // ECDSA signature length
        require(sigCount > 0, "No signatures provided");
        
        address[] memory signersArray = new address[](sigCount);
        bytes32 ethSignedMessageHash = hash.toEthSignedMessageHash();

        for (uint256 i = 0; i < sigCount; i++) {
            bytes memory sig = new bytes(65);
            // Copy signature bytes from concatenated signatures
            assembly {
                mstore(add(sig, 0x20), mload(add(signatures, add(0x20, mul(i, 65)))))
                mstore(add(sig, 0x40), mload(add(signatures, add(0x40, mul(i, 65)))))
                mstore(add(sig, 0x60), mload(add(signatures, add(0x60, mul(i, 65)))))
            }
            signersArray[i] = ethSignedMessageHash.recover(sig);
        }

        return signersArray;
    }

    /**
     * @dev Allows the contract to receive ETH
     */
    receive() external payable {}
}