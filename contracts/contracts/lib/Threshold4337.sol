// SPDX-License-Identifier: MIT
pragma solidity 0.8.17;

import "@openzeppelin/contracts/utils/cryptography/ECDSA.sol";
import "@account-abstraction/contracts/interfaces/IAccount.sol";
import "@account-abstraction/contracts/core/EntryPoint.sol";


contract Threshold4337 is IAccount {
    using ECDSA for bytes32;

    // Multisig configuration
    address[] public signers;  // Multisig signers
    uint256 public threshold;  // Required number of signatures
    EntryPoint public entryPoint;  // ERC-4337 entry point

    mapping(address => bool) public isSigner; // Quick lookup for signers
    mapping(bytes32 => bool) public executedOps; // Track executed operations

    event OperationExecuted(bytes32 indexed operationHash, address indexed sender);

    constructor(address[] memory _signers, uint256 _threshold, address _entryPoint) {
        require(_signers.length >= _threshold, "Threshold exceeds signers count");
        signers = _signers;
        threshold = _threshold;
        entryPoint = EntryPoint(_entryPoint);

        for (uint256 i = 0; i < _signers.length; i++) {
            isSigner[_signers[i]] = true;
        }
    }

    // Validate the UserOperation (ERC-4337 requirement)
    function validateUserOp(
        UserOperation calldata userOp,
        bytes32 userOpHash,
        uint256 missingWalletFunds
    ) external override returns (uint256 validationData) {
        require(_verifyMultisigSignature(userOpHash, userOp.signature), "Invalid multisig signature");

        // Optional: Handle funding for gas (optional in ERC-4337)
        if (missingWalletFunds > 0) {
            (bool success, ) = msg.sender.call{value: missingWalletFunds}("");
            require(success, "Failed to fund wallet");
        }

        return 0; // Return 0 indicates successful validation
    }

    // Verify that the multisig threshold is met
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

    // Recover signers from signature
    function _recoverSigners(bytes32 hash, bytes memory signatures) internal pure returns (address[] memory) {
        uint256 sigCount = signatures.length / 65; // ECDSA signature length
        address[] memory signersArray = new address[](sigCount);

        for (uint256 i = 0; i < sigCount; i++) {
            bytes memory sig = new bytes(65);
            assembly {
                mstore(add(sig, 0x20), mload(add(signatures, add(0x20, mul(i, 65)))))
                mstore(add(sig, 0x40), mload(add(signatures, add(0x40, mul(i, 65)))))
                mstore(add(sig, 0x60), mload(add(signatures, add(0x60, mul(i, 65)))))
            }
            signersArray[i] = hash.toEthSignedMessageHash().recover(sig);
        }

        return signersArray;
    }

    // Execute a transaction only if the multisig threshold is met
    function executeTransaction(
        address to,
        uint256 value,
        bytes calldata data,
        bytes memory signatures
    ) external {
        bytes32 operationHash = keccak256(abi.encodePacked(to, value, data, block.number));
        require(!executedOps[operationHash], "Operation already executed");
        require(_verifyMultisigSignature(operationHash, signatures), "Invalid signatures");

        executedOps[operationHash] = true;
        (bool success, ) = to.call{value: value}(data);
        require(success, "Transaction failed");

        emit OperationExecuted(operationHash, msg.sender);
    }

    receive() external payable {}
}
