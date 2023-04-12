"""
This file is part of nucypher.

nucypher is free software: you can redistribute it and/or modify
it under the terms of the GNU Affero General Public License as published by
the Free Software Foundation, either version 3 of the License, or
(at your option) any later version.

nucypher is distributed in the hope that it will be useful,
but WITHOUT ANY WARRANTY; without even the implied warranty of
MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
GNU Affero General Public License for more details.

You should have received a copy of the GNU Affero General Public License
along with nucypher.  If not, see <https://www.gnu.org/licenses/>.
"""
import ape
from web3 import Web3
from eth_utils import to_checksum_address

CONFIRMATION_SLOT = 1
MIN_AUTHORIZATION = Web3.to_wei(40_000, "ether")
MIN_OPERATOR_SECONDS = 24 * 60 * 60
NULL_ADDRESS = "0x" + "0" * 40  # TODO move to some test constants


def test_bond_operator(accounts, threshold_staking, pre_application, chain):
    creator, staking_provider_1, staking_provider_2, staking_provider_3, staking_provider_4, \
    operator1, operator2, operator3, owner3, beneficiary = accounts[0:]
    authorizer = creator
    min_authorization = MIN_AUTHORIZATION
    min_operator_seconds = MIN_OPERATOR_SECONDS

    # Prepare staking providers: two with intermediary contract and two just a staking provider
    threshold_staking.setRoles(staking_provider_1, sender=creator)
    threshold_staking.setStakes(staking_provider_1, min_authorization, 0, 0, sender=creator)
    threshold_staking.setRoles(staking_provider_2, sender=creator)
    threshold_staking.setStakes(
        staking_provider_2,
        min_authorization // 3,
        min_authorization // 3,
        min_authorization // 3 - 1,
        sender=creator,
    )
    threshold_staking.setRoles(
        staking_provider_3, owner3, beneficiary, authorizer, sender=creator
    )
    threshold_staking.setStakes(staking_provider_3, 0, min_authorization, 0, sender=creator)
    threshold_staking.setRoles(staking_provider_4, sender=creator)
    threshold_staking.setStakes(staking_provider_4, 0, 0, min_authorization, sender=creator)

    assert pre_application.getOperatorFromStakingProvider(staking_provider_1) == NULL_ADDRESS
    assert pre_application.stakingProviderFromOperator(staking_provider_1) == NULL_ADDRESS
    assert pre_application.getOperatorFromStakingProvider(staking_provider_2) == NULL_ADDRESS
    assert pre_application.stakingProviderFromOperator(staking_provider_2) == NULL_ADDRESS
    assert pre_application.getOperatorFromStakingProvider(staking_provider_3) == NULL_ADDRESS
    assert pre_application.stakingProviderFromOperator(staking_provider_3) == NULL_ADDRESS
    assert pre_application.getOperatorFromStakingProvider(staking_provider_4) == NULL_ADDRESS
    assert pre_application.stakingProviderFromOperator(staking_provider_4) == NULL_ADDRESS

    # Staking provider can't confirm operator address because there is no operator by default
    with ape.reverts():
        pre_application.confirmOperatorAddress(sender=staking_provider_1)

    # Staking provider can't bond another staking provider as operator
    with ape.reverts():
        pre_application.bondOperator(
            staking_provider_1, staking_provider_2, sender=staking_provider_1
        )

    # Staking provider can't bond operator if stake is less than minimum
    with ape.reverts():
        pre_application.bondOperator(staking_provider_2, operator1, sender=staking_provider_2)

    # Only staking provider or stake owner can bond operator
    with ape.reverts():
        pre_application.bondOperator(staking_provider_3, operator1, sender=beneficiary)
    with ape.reverts():
        pre_application.bondOperator(staking_provider_3, operator1, sender=authorizer)

    # Staking provider bonds operator and now operator can make a confirmation
    tx = pre_application.bondOperator(staking_provider_3, operator1, sender=owner3)
    timestamp = tx.timestamp
    assert pre_application.getOperatorFromStakingProvider(staking_provider_3) == operator1
    assert pre_application.stakingProviderFromOperator(operator1) == staking_provider_3
    assert not pre_application.stakingProviderInfo(staking_provider_3)[CONFIRMATION_SLOT]
    assert not pre_application.isOperatorConfirmed(operator1)
    assert pre_application.getStakingProvidersLength() == 1
    assert pre_application.stakingProviders(0) == staking_provider_3

    # No active stakingProviders before confirmation
    all_locked, staking_providers = pre_application.getActiveStakingProviders(0, 0)
    assert all_locked == 0
    assert len(staking_providers) == 0

    pre_application.confirmOperatorAddress(sender=operator1)
    assert pre_application.stakingProviderInfo(staking_provider_3)[CONFIRMATION_SLOT]
    assert pre_application.isOperatorConfirmed(operator1)

    events = pre_application.OperatorBonded.from_receipt(tx)
    assert len(events) == 1
    event = events[0]
    assert event["stakingProvider"] == staking_provider_3
    assert event["operator"] == operator1
    assert event["startTimestamp"] == timestamp

    # After confirmation operator is becoming active
    all_locked, staking_providers = pre_application.getActiveStakingProviders(0, 0)
    assert all_locked == min_authorization
    assert len(staking_providers) == 1
    assert to_checksum_address(staking_providers[0][0]) == staking_provider_3
    assert staking_providers[0][1] == min_authorization

    # Operator is in use so other stakingProviders can't bond him
    with ape.reverts():
        pre_application.bondOperator(staking_provider_4, operator1, sender=staking_provider_4)

    # # Operator can't be a staking provider
    # threshold_staking.setRoles(operator1, sender=creator)
    # threshold_staking.setStakes(operator1, min_authorization, 0, 0, sender=creator)
    # with ape.reverts():
    #     threshold_staking.increaseAuthorization(
    #         operator1, min_authorization, pre_application.address, {'from': operator1})

    # Can't bond operator twice too soon
    with ape.reverts():
        pre_application.bondOperator(staking_provider_3, operator2, sender=staking_provider_3)

    # She can't unbond her operator too, until enough time has passed
    with ape.reverts():
        pre_application.bondOperator(staking_provider_3, NULL_ADDRESS, sender=staking_provider_3)

    # Let's advance some time and unbond the operator
    chain.pending_timestamp += min_operator_seconds
    tx = pre_application.bondOperator(
        staking_provider_3, NULL_ADDRESS, sender=staking_provider_3
    )
    timestamp = tx.timestamp
    assert pre_application.getOperatorFromStakingProvider(staking_provider_3) == NULL_ADDRESS
    assert pre_application.stakingProviderFromOperator(staking_provider_3) == NULL_ADDRESS
    assert pre_application.stakingProviderFromOperator(operator1) == NULL_ADDRESS
    assert not pre_application.stakingProviderInfo(staking_provider_3)[CONFIRMATION_SLOT]
    assert not pre_application.isOperatorConfirmed(operator1)
    assert pre_application.getStakingProvidersLength() == 1
    assert pre_application.stakingProviders(0) == staking_provider_3

    # Resetting operator removes from active list before next confirmation
    all_locked, staking_providers = pre_application.getActiveStakingProviders(0, 0)
    assert all_locked == 0
    assert len(staking_providers) == 0

    events = pre_application.OperatorBonded.from_receipt(tx)
    assert len(events) == 1
    event = events[0]
    assert event["stakingProvider"] == staking_provider_3
    # Now the operator has been unbonded ...
    assert event["operator"] == NULL_ADDRESS
    # ... with a new starting period.
    assert event["startTimestamp"] == timestamp

    # The staking provider can bond now a new operator, without waiting additional time.
    tx = pre_application.bondOperator(staking_provider_3, operator2, sender=staking_provider_3)
    timestamp = tx.timestamp
    assert pre_application.getOperatorFromStakingProvider(staking_provider_3) == operator2
    assert pre_application.stakingProviderFromOperator(operator2) == staking_provider_3
    assert not pre_application.stakingProviderInfo(staking_provider_3)[CONFIRMATION_SLOT]
    assert not pre_application.isOperatorConfirmed(operator2)
    assert pre_application.getStakingProvidersLength() == 1
    assert pre_application.stakingProviders(0) == staking_provider_3

    events = pre_application.OperatorBonded.from_receipt(tx)
    assert len(events) == 1
    event = events[0]
    assert event["stakingProvider"] == staking_provider_3
    assert event["operator"] == operator2
    assert event["startTimestamp"] == timestamp

    # Now the previous operator can no longer make a confirmation
    with ape.reverts():
        pre_application.confirmOperatorAddress(sender=operator1)
    # Only new operator can
    pre_application.confirmOperatorAddress(sender=operator2)
    assert not pre_application.isOperatorConfirmed(operator1)
    assert pre_application.isOperatorConfirmed(operator2)
    assert pre_application.stakingProviderInfo(staking_provider_3)[CONFIRMATION_SLOT]

    # Another staker can bond a free operator
    tx = pre_application.bondOperator(staking_provider_4, operator1, sender=staking_provider_4)
    timestamp = tx.timestamp
    assert pre_application.getOperatorFromStakingProvider(staking_provider_4) == operator1
    assert pre_application.stakingProviderFromOperator(operator1) == staking_provider_4
    assert not pre_application.isOperatorConfirmed(operator1)
    assert not pre_application.stakingProviderInfo(staking_provider_4)[CONFIRMATION_SLOT]
    assert pre_application.getStakingProvidersLength() == 2
    assert pre_application.stakingProviders(1) == staking_provider_4

    events = pre_application.OperatorBonded.from_receipt(tx)
    assert len(events) == 1
    event = events[0]
    assert event["stakingProvider"] == staking_provider_4
    assert event["operator"] == operator1
    assert event["startTimestamp"] == timestamp

    # # The first operator still can't be a staking provider
    # threshold_staking.setRoles(operator1, sender=creator)
    # threshold_staking.setStakes(operator1, min_authorization, 0, 0, sender=creator)
    # with ape.reverts():
    #     threshold_staking.increaseAuthorization(
    #         operator1, min_authorization, pre_application.address, {'from': operator1})

    # Bond operator again
    pre_application.confirmOperatorAddress(sender=operator1)
    assert pre_application.isOperatorConfirmed(operator1)
    assert pre_application.stakingProviderInfo(staking_provider_4)[CONFIRMATION_SLOT]
    chain.pending_timestamp += min_operator_seconds
    tx = pre_application.bondOperator(staking_provider_4, operator3, sender=staking_provider_4)
    timestamp = tx.timestamp
    assert pre_application.getOperatorFromStakingProvider(staking_provider_4) == operator3
    assert pre_application.stakingProviderFromOperator(operator3) == staking_provider_4
    assert pre_application.stakingProviderFromOperator(operator1) == NULL_ADDRESS
    assert not pre_application.isOperatorConfirmed(operator3)
    assert not pre_application.isOperatorConfirmed(operator1)
    assert not pre_application.stakingProviderInfo(staking_provider_4)[CONFIRMATION_SLOT]
    assert pre_application.getStakingProvidersLength() == 2
    assert pre_application.stakingProviders(1) == staking_provider_4

    # Resetting operator removes from active list before next confirmation
    all_locked, staking_providers = pre_application.getActiveStakingProviders(1, 0)
    assert all_locked == 0
    assert len(staking_providers) == 0

    events = pre_application.OperatorBonded.from_receipt(tx)
    assert len(events) == 1
    event = events[0]
    assert event["stakingProvider"] == staking_provider_4
    assert event["operator"] == operator3
    assert event["startTimestamp"] == timestamp

    # The first operator is free and can deposit tokens and become a staker
    threshold_staking.setRoles(operator1, sender=creator)
    threshold_staking.setStakes(
        operator1,
        min_authorization // 3,
        min_authorization // 3,
        min_authorization // 3,
        sender=creator,
    )
    # threshold_staking.increaseAuthorization(
    #     operator1, min_authorization, pre_application.address, {'from': operator1})
    assert pre_application.getOperatorFromStakingProvider(operator1) == NULL_ADDRESS
    assert pre_application.stakingProviderFromOperator(operator1) == NULL_ADDRESS

    chain.pending_timestamp += min_operator_seconds

    # Staking provider can't bond the first operator again because operator is a provider now
    with ape.reverts():
        pre_application.bondOperator(staking_provider_4, operator1, sender=staking_provider_4)

    # Provider without intermediary contract can bond itself as operator
    # (Probably not best idea, but whatever)
    tx = pre_application.bondOperator(
        staking_provider_1, staking_provider_1, sender=staking_provider_1
    )
    timestamp = tx.timestamp
    assert pre_application.getOperatorFromStakingProvider(staking_provider_1) == staking_provider_1
    assert pre_application.stakingProviderFromOperator(staking_provider_1) == staking_provider_1
    assert pre_application.getStakingProvidersLength() == 3
    assert pre_application.stakingProviders(2) == staking_provider_1

    events = pre_application.OperatorBonded.from_receipt(tx)
    assert len(events) == 1
    event = events[0]
    assert event["stakingProvider"] == staking_provider_1
    assert event["operator"] == staking_provider_1
    assert event["startTimestamp"] == timestamp

    # If stake will be less than minimum then confirmation is not possible
    threshold_staking.setStakes(staking_provider_1, 0, min_authorization - 1, 0, sender=creator)

    with ape.reverts():
        pre_application.confirmOperatorAddress(sender=staking_provider_1)

    # Now provider can make a confirmation
    threshold_staking.setStakes(staking_provider_1, 0, 0, min_authorization, sender=creator)
    pre_application.confirmOperatorAddress(sender=staking_provider_1)

    # If stake will be less than minimum then provider is not active
    all_locked, staking_providers = pre_application.getActiveStakingProviders(0, 0)
    assert all_locked == 2 * min_authorization
    assert len(staking_providers) == 2
    assert to_checksum_address(staking_providers[0][0]) == staking_provider_3
    assert staking_providers[0][1] == min_authorization
    assert to_checksum_address(staking_providers[1][0]) == staking_provider_1
    assert staking_providers[1][1] == min_authorization
    threshold_staking.setStakes(staking_provider_1, 0, min_authorization - 1, 0, sender=creator)
    all_locked, staking_providers = pre_application.getActiveStakingProviders(1, 0)
    assert all_locked == 0
    assert len(staking_providers) == 0


def test_confirm_address(accounts, threshold_staking, pre_application, chain, project):
    creator, staking_provider, operator, *everyone_else = accounts[0:]
    min_authorization = MIN_AUTHORIZATION
    min_operator_seconds = MIN_OPERATOR_SECONDS

    # Operator must be associated with provider that has minimum amount of tokens
    with ape.reverts():
        pre_application.confirmOperatorAddress(sender=staking_provider)
    threshold_staking.setRoles(staking_provider, sender=creator)
    threshold_staking.setStakes(staking_provider, min_authorization - 1, 0, 0, sender=creator)
    with ape.reverts():
        pre_application.confirmOperatorAddress(sender=staking_provider)

    # Deploy intermediary contract
    intermediary = creator.deploy(project.Intermediary, pre_application.address, sender=creator)

    # Bond contract as an operator
    threshold_staking.setStakes(staking_provider, min_authorization, 0, 0, sender=creator)
    pre_application.bondOperator(staking_provider, intermediary.address, sender=staking_provider)

    # But can't make a confirmation using an intermediary contract
    with ape.reverts():
        intermediary.confirmOperatorAddress(sender=staking_provider)

    # Bond operator again and make confirmation
    chain.pending_timestamp += min_operator_seconds
    pre_application.bondOperator(staking_provider, operator, sender=staking_provider)
    tx = pre_application.confirmOperatorAddress(sender=operator)
    assert pre_application.isOperatorConfirmed(operator)
    assert pre_application.stakingProviderInfo(staking_provider)[CONFIRMATION_SLOT]

    events = pre_application.OperatorConfirmed.from_receipt(tx)
    assert len(events) == 1
    event = events[0]
    assert event["stakingProvider"] == staking_provider
    assert event["operator"] == operator

    # Can't confirm twice
    with ape.reverts():
        pre_application.confirmOperatorAddress(sender=operator)
