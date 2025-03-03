import ape
import pytest
from ape.utils import ZERO_ADDRESS
from eth_account import Account
from eth_account.messages import encode_defunct
from web3 import Web3

# UserOperation structure mimicking the one in EntryPoint
class UserOperation:
    def __init__(self, sender=None, nonce=0, initCode=b'', callData=b'', callGasLimit=0, 
                verificationGasLimit=0, preVerificationGas=0, maxFeePerGas=0, 
                maxPriorityFeePerGas=0, paymasterAndData=b'', signature=b''):
        self.sender = sender
        self.nonce = nonce
        self.initCode = initCode
        self.callData = callData
        self.callGasLimit = callGasLimit
        self.verificationGasLimit = verificationGasLimit
        self.preVerificationGas = preVerificationGas
        self.maxFeePerGas = maxFeePerGas
        self.maxPriorityFeePerGas = maxPriorityFeePerGas
        self.paymasterAndData = paymasterAndData
        self.signature = signature


@pytest.fixture(scope="module")
def signers(accounts):
    return sorted(accounts[:5], key=lambda x: x.address.lower())


@pytest.fixture(scope="module")
def threshold():
    return 3  # Requiring 3 out of 5 signatures


@pytest.fixture(scope="module")
def deployer(accounts):
    return accounts[5]


@pytest.fixture(scope="module")
def entry_point(project, deployer):
    # Deploy a mock EntryPoint for testing
    return project.EntryPointMock.deploy(sender=deployer)


@pytest.fixture(scope="module")
def threshold4337(project, signers, threshold, entry_point, deployer):
    contract = project.Threshold4337.deploy(
        [s.address for s in signers],
        threshold,
        entry_point.address,
        sender=deployer
    )
    return contract


@pytest.fixture
def user_op_hash():
    return Web3.keccak(text="test operation hash")


def sign_message(account, message_hash):
    # Create an Ethereum signed message
    message = encode_defunct(message_hash)
    signed_message = account.sign_message(message)
    return signed_message.signature


def generate_signatures(signers, message_hash, count):
    # Generate signatures from the first 'count' signers
    signatures = b''
    for i in range(count):
        sig = sign_message(signers[i], message_hash)
        signatures += sig
    return signatures


def test_constructor(threshold4337, signers, threshold, entry_point):
    # Test that the contract is initialized with the correct parameters
    for i, signer in enumerate(signers):
        assert threshold4337.signers(i) == signer.address
        assert threshold4337.isSigner(signer.address) is True
    
    assert threshold4337.threshold() == threshold
    assert threshold4337.entryPoint() == entry_point.address


def test_verify_multisig_signature(threshold4337, signers, user_op_hash):
    # Test signature verification with different number of signers
    
    # Test with exactly the threshold number of signatures
    signatures = generate_signatures(signers, user_op_hash, threshold4337.threshold())
    tx = threshold4337.exposed_verifyMultisigSignature(user_op_hash, signatures)
    assert tx.return_value is True
    
    # Test with more than the threshold number of signatures
    signatures = generate_signatures(signers, user_op_hash, len(signers))
    tx = threshold4337.exposed_verifyMultisigSignature(user_op_hash, signatures)
    assert tx.return_value is True
    
    # Test with less than the threshold number of signatures
    signatures = generate_signatures(signers, user_op_hash, threshold4337.threshold() - 1)
    tx = threshold4337.exposed_verifyMultisigSignature(user_op_hash, signatures)
    assert tx.return_value is False


def test_validate_user_op(threshold4337, signers, user_op_hash, entry_point):
    # Create a valid UserOperation
    threshold_count = threshold4337.threshold()
    signatures = generate_signatures(signers, user_op_hash, threshold_count)
    
    user_op = UserOperation(
        sender=threshold4337.address,
        signature=signatures
    )
    
    # Test with valid signatures and no missing funds
    result = threshold4337.validateUserOp(user_op, user_op_hash, 0, sender=entry_point)
    assert result == 0  # 0 indicates successful validation
    
    # Test with valid signatures and missing funds
    # First, send some ETH to the contract
    deployer_account = signers[0]
    initial_balance = Web3.to_wei(1, 'ether')
    deployer_account.transfer(threshold4337.address, initial_balance)
    
    missing_funds = Web3.to_wei(0.1, 'ether')
    entry_point_balance_before = Web3.to_wei(0, 'ether')
    
    # Execute validation with missing funds
    threshold4337.validateUserOp(user_op, user_op_hash, missing_funds, sender=entry_point)
    
    # Verify funds were sent to entry point
    entry_point_balance_after = Web3.to_wei(missing_funds, 'ether')
    assert entry_point_balance_after - entry_point_balance_before == missing_funds


def test_validate_user_op_fails_with_invalid_signatures(threshold4337, signers, user_op_hash, entry_point):
    # Test with insufficient signatures
    insufficient_sigs = generate_signatures(signers, user_op_hash, threshold4337.threshold() - 1)
    
    user_op = UserOperation(
        sender=threshold4337.address,
        signature=insufficient_sigs
    )
    
    with ape.reverts("Invalid multisig signature"):
        threshold4337.validateUserOp(user_op, user_op_hash, 0, sender=entry_point)


def test_execute_transaction(threshold4337, signers, deployer):
    # Create transaction data
    to_address = deployer.address
    value = Web3.to_wei(0.01, 'ether')
    data = b''
    
    # Fund the contract
    deployer.transfer(threshold4337.address, Web3.to_wei(0.1, 'ether'))
    
    # Create operation hash
    current_block = ape.chain.blocks[-1].number
    operation_hash = Web3.keccak(
        b''.join([
            to_address.encode(),
            Web3.to_bytes(value),
            data,
            Web3.to_bytes(current_block)
        ])
    )
    
    # Generate signatures
    signatures = generate_signatures(signers, operation_hash, threshold4337.threshold())
    
    # Execute the transaction
    tx = threshold4337.executeTransaction(
        to_address, value, data, signatures, sender=deployer
    )
    
    # Verify the transaction executed successfully
    events = threshold4337.OperationExecuted.from_receipt(tx)
    assert len(events) == 1
    assert events[0].operationHash == operation_hash
    assert events[0].sender == deployer.address
    
    # Verify the operation is marked as executed
    assert threshold4337.executedOps(operation_hash) is True


def test_execute_transaction_fails_on_duplicate(threshold4337, signers, deployer):
    # Create transaction data
    to_address = deployer.address
    value = 0
    data = b''
    
    # Create operation hash
    current_block = ape.chain.blocks[-1].number
    operation_hash = Web3.keccak(
        b''.join([
            to_address.encode(),
            Web3.to_bytes(value),
            data,
            Web3.to_bytes(current_block)
        ])
    )
    
    # Generate signatures
    signatures = generate_signatures(signers, operation_hash, threshold4337.threshold())
    
    # Execute the transaction first time
    threshold4337.executeTransaction(
        to_address, value, data, signatures, sender=deployer
    )
    
    # Attempt to execute the same transaction again
    with ape.reverts("Operation already executed"):
        threshold4337.executeTransaction(
            to_address, value, data, signatures, sender=deployer
        )


def test_execute_transaction_fails_with_invalid_signatures(threshold4337, signers, deployer):
    # Create transaction data
    to_address = deployer.address
    value = 0
    data = b''
    
    # Create operation hash
    current_block = ape.chain.blocks[-1].number
    operation_hash = Web3.keccak(
        b''.join([
            to_address.encode(),
            Web3.to_bytes(value),
            data,
            Web3.to_bytes(current_block)
        ])
    )
    
    # Generate insufficient signatures
    signatures = generate_signatures(signers, operation_hash, threshold4337.threshold() - 1)
    
    # Attempt to execute with insufficient signatures
    with ape.reverts("Invalid signatures"):
        threshold4337.executeTransaction(
            to_address, value, data, signatures, sender=deployer
        )


def test_recover_signers(threshold4337, signers, user_op_hash):
    # Test that signers are correctly recovered from signatures
    signatures = generate_signatures(signers, user_op_hash, 3)
    
    # Expose the internal function for testing
    tx = threshold4337.exposed_recoverSigners(user_op_hash, signatures)
    recovered_signers = tx.return_value
    
    # Verify the recovered signers match the expected signers
    assert len(recovered_signers) == 3
    for i in range(3):
        assert recovered_signers[i] == signers[i].address


def test_receive_function(threshold4337, deployer):
    # Test the contract can receive ETH
    initial_balance = threshold4337.balance
    amount = Web3.to_wei(0.1, 'ether')
    
    # Send ETH to the contract
    deployer.transfer(threshold4337.address, amount)
    
    # Verify the contract balance increased
    assert threshold4337.balance == initial_balance + amount
