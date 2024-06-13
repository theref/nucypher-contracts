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
import os
from enum import IntEnum

import ape
import pytest
from eth_account.messages import encode_defunct
from web3 import Web3

BASE_FEE_RATE = 42
MAX_NODES = 10
ENCRYPTORS_FEE_RATE = 77


ERC20_SUPPLY = 10**24
ONE_DAY = 24 * 60 * 60
DURATION = 10 * ONE_DAY

PACKAGE_DURATION = 3 * DURATION
YELLOW_PERIOD = ONE_DAY
RED_PERIOD = 5 * ONE_DAY

BASE_FEE = BASE_FEE_RATE * PACKAGE_DURATION * MAX_NODES

RitualState = IntEnum(
    "RitualState",
    [
        "NON_INITIATED",
        "DKG_AWAITING_TRANSCRIPTS",
        "DKG_AWAITING_AGGREGATIONS",
        "DKG_TIMEOUT",
        "DKG_INVALID",
        "ACTIVE",
        "EXPIRED",
    ],
    start=0,
)


@pytest.fixture(scope="module")
def treasury(accounts):
    return accounts[1]


@pytest.fixture(scope="module")
def adopter(accounts):
    return accounts[2]


@pytest.fixture()
def erc20(project, adopter):
    token = project.TestToken.deploy(ERC20_SUPPLY, sender=adopter)
    return token


@pytest.fixture()
def coordinator(project, creator):
    contract = project.CoordinatorForBqETHSubscriptionMock.deploy(
        sender=creator,
    )
    return contract


@pytest.fixture()
def subscription(project, creator, coordinator, erc20, treasury, adopter):
    contract = project.BqETHSubscription.deploy(
        coordinator.address,
        erc20.address,
        treasury,
        adopter,
        BASE_FEE_RATE,
        ENCRYPTORS_FEE_RATE,
        MAX_NODES,
        PACKAGE_DURATION,
        YELLOW_PERIOD,
        RED_PERIOD,
        sender=creator,
    )
    coordinator.setFeeModel(contract.address, sender=creator)
    return contract


@pytest.fixture()
def global_allow_list(project, creator, coordinator, subscription, treasury):
    contract = project.GlobalAllowList.deploy(
        coordinator.address, subscription.address, sender=creator
    )
    subscription.initialize(contract.address, sender=treasury)
    return contract


def test_pay_subscription(erc20, subscription, adopter, chain):
    erc20.approve(subscription.address, 10 * BASE_FEE, sender=adopter)

    # First payment
    balance_before = erc20.balanceOf(adopter)
    assert subscription.baseFees() == BASE_FEE
    assert subscription.startOfSubscription() == 0
    assert subscription.getEndOfSubscription() == 0
    assert subscription.getCurrentPeriodNumber() == 0
    assert subscription.billingInfo(0) == (False, 0)

    tx = subscription.payForSubscription(0, sender=adopter)
    timestamp = chain.pending_timestamp - 1
    assert subscription.startOfSubscription() == timestamp
    assert subscription.getEndOfSubscription() == timestamp + PACKAGE_DURATION
    assert subscription.getCurrentPeriodNumber() == 0
    assert subscription.billingInfo(0) == (True, 0)
    assert subscription.billingInfo(1) == (False, 0)
    balance_after = erc20.balanceOf(adopter)
    assert balance_after + BASE_FEE == balance_before
    assert erc20.balanceOf(subscription.address) == BASE_FEE

    events = subscription.SubscriptionPaid.from_receipt(tx)
    assert events == [
        subscription.SubscriptionPaid(
            subscriber=adopter,
            amount=BASE_FEE,
            encryptorSlots=0,
            endOfSubscription=timestamp + PACKAGE_DURATION,
        )
    ]

    # Top up
    encryptor_slots = 10
    encryptor_fees = ENCRYPTORS_FEE_RATE * PACKAGE_DURATION * encryptor_slots
    balance_before = erc20.balanceOf(adopter)
    tx = subscription.payForSubscription(10, sender=adopter)
    end_subscription = timestamp + 2 * PACKAGE_DURATION
    assert subscription.getEndOfSubscription() == end_subscription
    balance_after = erc20.balanceOf(adopter)
    assert balance_after + BASE_FEE + encryptor_fees == balance_before
    assert erc20.balanceOf(subscription.address) == 2 * BASE_FEE + encryptor_fees
    assert subscription.getCurrentPeriodNumber() == 0
    assert subscription.billingInfo(0) == (True, 0)
    assert subscription.billingInfo(1) == (True, encryptor_slots)

    events = subscription.SubscriptionPaid.from_receipt(tx)
    assert events == [
        subscription.SubscriptionPaid(
            subscriber=adopter,
            amount=BASE_FEE + encryptor_fees,
            encryptorSlots=encryptor_slots,
            endOfSubscription=end_subscription,
        )
    ]

    # Can't pay in advance more than one time cycle
    with ape.reverts("Next billing period already paid"):
        subscription.payForSubscription(0, sender=adopter)

    # Can't pay after red period is over
    chain.pending_timestamp = end_subscription + YELLOW_PERIOD + RED_PERIOD + 1
    assert subscription.getCurrentPeriodNumber() == 2
    with ape.reverts("Subscription is over"):
        subscription.payForSubscription(0, sender=adopter)


def test_pay_encryptor_slots(erc20, subscription, adopter, chain):
    encryptor_slots = 10
    assert (
        subscription.encryptorFees(encryptor_slots, PACKAGE_DURATION)
        == encryptor_slots * PACKAGE_DURATION * ENCRYPTORS_FEE_RATE
    )

    erc20.approve(subscription.address, 10 * BASE_FEE, sender=adopter)

    with ape.reverts("Current billing period must be paid"):
        subscription.payForEncryptorSlots(encryptor_slots, sender=adopter)

    subscription.payForSubscription(encryptor_slots, sender=adopter)
    timestamp = chain.pending_timestamp - 1
    subscription.payForSubscription(0, sender=adopter)
    assert subscription.billingInfo(0) == (True, encryptor_slots)
    assert subscription.billingInfo(1) == (True, 0)

    duration = PACKAGE_DURATION // 3
    chain.pending_timestamp = timestamp + duration
    encryptor_fees = encryptor_slots * (PACKAGE_DURATION - duration) * ENCRYPTORS_FEE_RATE
    assert (
        subscription.encryptorFees(encryptor_slots, PACKAGE_DURATION - duration) == encryptor_fees
    )

    adopter_balance_before = erc20.balanceOf(adopter)
    subscription_balance_before = erc20.balanceOf(subscription.address)
    tx = subscription.payForEncryptorSlots(encryptor_slots, sender=adopter)
    adopter_balance_after = erc20.balanceOf(adopter)
    subscription_balance_after = erc20.balanceOf(subscription.address)
    assert adopter_balance_after + encryptor_fees == adopter_balance_before
    assert subscription_balance_before + encryptor_fees == subscription_balance_after
    assert subscription.billingInfo(0) == (True, 2 * encryptor_slots)
    assert subscription.billingInfo(1) == (True, 0)

    events = subscription.EncryptorSlotsPaid.from_receipt(tx)
    assert events == [
        subscription.EncryptorSlotsPaid(
            subscriber=adopter,
            amount=encryptor_fees,
            encryptorSlots=encryptor_slots,
            endOfCurrentPeriod=timestamp + PACKAGE_DURATION,
        )
    ]

    duration = PACKAGE_DURATION // 5
    chain.pending_timestamp = timestamp + PACKAGE_DURATION + duration
    encryptor_fees = encryptor_slots * (PACKAGE_DURATION - duration) * ENCRYPTORS_FEE_RATE

    adopter_balance_before = erc20.balanceOf(adopter)
    subscription_balance_before = erc20.balanceOf(subscription.address)
    tx = subscription.payForEncryptorSlots(encryptor_slots, sender=adopter)
    adopter_balance_after = erc20.balanceOf(adopter)
    subscription_balance_after = erc20.balanceOf(subscription.address)
    assert adopter_balance_after + encryptor_fees == adopter_balance_before
    assert subscription_balance_before + encryptor_fees == subscription_balance_after
    assert subscription.billingInfo(0) == (True, 2 * encryptor_slots)
    assert subscription.billingInfo(1) == (True, encryptor_slots)

    events = subscription.EncryptorSlotsPaid.from_receipt(tx)
    assert events == [
        subscription.EncryptorSlotsPaid(
            subscriber=adopter,
            amount=encryptor_fees,
            encryptorSlots=encryptor_slots,
            endOfCurrentPeriod=timestamp + 2 * PACKAGE_DURATION,
        )
    ]

    chain.pending_timestamp = timestamp + 2 * PACKAGE_DURATION + duration
    with ape.reverts("Current billing period must be paid"):
        subscription.payForEncryptorSlots(encryptor_slots, sender=adopter)


def test_withdraw(erc20, subscription, adopter, treasury):
    erc20.approve(subscription.address, 10 * BASE_FEE, sender=adopter)

    with ape.reverts("Only the beneficiary can call this method"):
        subscription.withdrawToBeneficiary(1, sender=adopter)

    with ape.reverts("Insufficient balance available"):
        subscription.withdrawToBeneficiary(1, sender=treasury)

    subscription.payForSubscription(0, sender=adopter)

    with ape.reverts("Insufficient balance available"):
        subscription.withdrawToBeneficiary(BASE_FEE + 1, sender=treasury)

    tx = subscription.withdrawToBeneficiary(BASE_FEE, sender=treasury)
    assert erc20.balanceOf(treasury) == BASE_FEE
    assert erc20.balanceOf(subscription.address) == 0

    events = subscription.WithdrawalToBeneficiary.from_receipt(tx)
    assert events == [subscription.WithdrawalToBeneficiary(beneficiary=treasury, amount=BASE_FEE)]


def test_process_ritual_payment(
    erc20, subscription, coordinator, global_allow_list, adopter, treasury
):
    ritual_id = 7
    number_of_providers = 6

    with ape.reverts("Only the Coordinator can call this method"):
        subscription.processRitualPayment(
            adopter, ritual_id, number_of_providers, DURATION, sender=treasury
        )
    with ape.reverts("Only adopter can initiate ritual"):
        coordinator.processRitualPayment(
            treasury, ritual_id, number_of_providers, DURATION, sender=treasury
        )
    with ape.reverts("Subscription has to be paid first"):
        coordinator.processRitualPayment(
            adopter, ritual_id, number_of_providers, DURATION, sender=treasury
        )

    erc20.approve(subscription.address, 10 * BASE_FEE, sender=adopter)
    subscription.payForSubscription(0, sender=adopter)

    with ape.reverts("Ritual parameters exceed available in package"):
        coordinator.processRitualPayment(
            adopter, ritual_id, MAX_NODES + 1, DURATION, sender=treasury
        )
    with ape.reverts("Ritual parameters exceed available in package"):
        coordinator.processRitualPayment(
            adopter,
            ritual_id,
            number_of_providers,
            PACKAGE_DURATION + YELLOW_PERIOD + RED_PERIOD + 1,
            sender=treasury,
        )

    coordinator.setRitual(ritual_id, RitualState.NON_INITIATED, 0, treasury, sender=treasury)

    with ape.reverts("Access controller for ritual must be approved"):
        coordinator.processRitualPayment(
            adopter,
            ritual_id,
            MAX_NODES,
            PACKAGE_DURATION + YELLOW_PERIOD + RED_PERIOD - 4,
            sender=treasury,
        )

    assert subscription.activeRitualId() == subscription.INACTIVE_RITUAL_ID()
    coordinator.setRitual(
        ritual_id,
        RitualState.DKG_AWAITING_TRANSCRIPTS,
        0,
        global_allow_list.address,
        sender=treasury,
    )
    coordinator.processRitualPayment(
        adopter, ritual_id, number_of_providers, DURATION, sender=treasury
    )
    assert subscription.activeRitualId() == ritual_id

    new_ritual_id = ritual_id + 1
    coordinator.setRitual(
        new_ritual_id, RitualState.ACTIVE, 0, global_allow_list.address, sender=treasury
    )
    with ape.reverts("Only failed rituals allowed to be reinitiated"):
        coordinator.processRitualPayment(
            adopter, new_ritual_id, number_of_providers, DURATION, sender=treasury
        )

    coordinator.setRitual(
        ritual_id, RitualState.DKG_INVALID, 0, global_allow_list.address, sender=treasury
    )
    coordinator.processRitualPayment(
        adopter, new_ritual_id, number_of_providers, DURATION, sender=treasury
    )
    assert subscription.activeRitualId() == new_ritual_id

    ritual_id = new_ritual_id
    new_ritual_id = ritual_id + 1
    coordinator.setRitual(
        new_ritual_id, RitualState.ACTIVE, 0, global_allow_list.address, sender=treasury
    )
    coordinator.setRitual(
        ritual_id, RitualState.DKG_TIMEOUT, 0, global_allow_list.address, sender=treasury
    )
    coordinator.processRitualPayment(
        adopter, new_ritual_id, number_of_providers, DURATION, sender=treasury
    )
    assert subscription.activeRitualId() == new_ritual_id

    ritual_id = new_ritual_id
    new_ritual_id = ritual_id + 1
    coordinator.setRitual(
        new_ritual_id, RitualState.ACTIVE, 0, global_allow_list.address, sender=treasury
    )
    coordinator.setRitual(
        ritual_id, RitualState.EXPIRED, 0, global_allow_list.address, sender=treasury
    )
    coordinator.processRitualPayment(
        adopter, new_ritual_id, number_of_providers, DURATION, sender=treasury
    )
    assert subscription.activeRitualId() == new_ritual_id


def test_process_ritual_extending(
    erc20, subscription, coordinator, adopter, global_allow_list, treasury
):
    ritual_id = 6
    number_of_providers = 7

    with ape.reverts("Only the Coordinator can call this method"):
        subscription.processRitualExtending(
            adopter, ritual_id, number_of_providers, DURATION, sender=treasury
        )
    with ape.reverts("Ritual must be active"):
        coordinator.processRitualExtending(
            treasury, ritual_id, number_of_providers, DURATION, sender=treasury
        )

    erc20.approve(subscription.address, 10 * BASE_FEE, sender=adopter)
    subscription.payForSubscription(0, sender=adopter)
    coordinator.setRitual(
        ritual_id, RitualState.ACTIVE, 0, global_allow_list.address, sender=treasury
    )
    coordinator.processRitualPayment(
        adopter, ritual_id, number_of_providers, DURATION, sender=treasury
    )
    end_subscription = subscription.getEndOfSubscription()
    max_end_timestamp = end_subscription + YELLOW_PERIOD + RED_PERIOD

    new_ritual_id = ritual_id + 1
    with ape.reverts("Ritual must be active"):
        coordinator.processRitualExtending(
            treasury, new_ritual_id, number_of_providers, DURATION, sender=treasury
        )

    coordinator.setRitual(
        ritual_id,
        RitualState.DKG_INVALID,
        max_end_timestamp + 1,
        global_allow_list.address,
        sender=treasury,
    )

    with ape.reverts("Ritual parameters exceed available in package"):
        coordinator.processRitualExtending(
            treasury, ritual_id, number_of_providers, DURATION, sender=treasury
        )

    coordinator.setRitual(
        ritual_id,
        RitualState.DKG_INVALID,
        max_end_timestamp,
        global_allow_list.address,
        sender=treasury,
    )
    coordinator.processRitualExtending(
        adopter, ritual_id, number_of_providers, DURATION, sender=treasury
    )

    coordinator.setRitual(
        new_ritual_id,
        RitualState.DKG_INVALID,
        max_end_timestamp,
        global_allow_list.address,
        sender=treasury,
    )
    coordinator.processRitualPayment(
        adopter, new_ritual_id, number_of_providers, DURATION, sender=treasury
    )
    with ape.reverts("Ritual must be active"):
        coordinator.processRitualExtending(
            treasury, ritual_id, number_of_providers, DURATION, sender=treasury
        )
    coordinator.processRitualPayment(
        adopter, new_ritual_id, number_of_providers, DURATION, sender=treasury
    )


def test_before_set_authorization(
    erc20, subscription, coordinator, adopter, global_allow_list, treasury, creator, chain
):
    ritual_id = 6
    number_of_providers = 7

    assert subscription.address == global_allow_list.feeModel()

    with ape.reverts("Only Access Controller can call this method"):
        subscription.beforeSetAuthorization(0, [creator], True, sender=adopter)

    with ape.reverts("Ritual must be active"):
        global_allow_list.authorize(0, [creator], sender=adopter)

    erc20.approve(subscription.address, 10 * BASE_FEE, sender=adopter)
    subscription.payForSubscription(0, sender=adopter)
    coordinator.setRitual(
        ritual_id, RitualState.ACTIVE, 0, global_allow_list.address, sender=treasury
    )
    coordinator.processRitualPayment(
        adopter, ritual_id, number_of_providers, DURATION, sender=treasury
    )

    with ape.reverts("Ritual must be active"):
        global_allow_list.authorize(0, [creator], sender=adopter)

    with ape.reverts("Encryptors slots filled up"):
        global_allow_list.authorize(ritual_id, [creator], sender=adopter)

    subscription.payForEncryptorSlots(2, sender=adopter)
    global_allow_list.authorize(ritual_id, [creator], sender=adopter)
    assert subscription.usedEncryptorSlots() == 1

    with ape.reverts("Encryptors slots filled up"):
        global_allow_list.authorize(ritual_id, [creator, adopter], sender=adopter)

    global_allow_list.deauthorize(ritual_id, [creator], sender=adopter)
    assert subscription.usedEncryptorSlots() == 0

    global_allow_list.authorize(ritual_id, [creator, adopter], sender=adopter)
    assert subscription.usedEncryptorSlots() == 2

    end_subscription = subscription.getEndOfSubscription()
    chain.pending_timestamp = end_subscription + 1

    with ape.reverts("Subscription has expired"):
        global_allow_list.authorize(ritual_id, [creator], sender=adopter)

    subscription.payForSubscription(0, sender=adopter)
    with ape.reverts("Encryptors slots filled up"):
        global_allow_list.authorize(ritual_id, [creator], sender=adopter)

    subscription.payForEncryptorSlots(3, sender=adopter)
    with ape.reverts("Encryptors slots filled up"):
        global_allow_list.authorize(ritual_id, [treasury, subscription.address], sender=adopter)
    global_allow_list.authorize(ritual_id, [treasury], sender=adopter)
    assert subscription.usedEncryptorSlots() == 3


def test_before_is_authorized(
    erc20, subscription, coordinator, adopter, global_allow_list, treasury, creator, chain
):
    ritual_id = 6

    w3 = Web3()
    data = os.urandom(32)
    digest = Web3.keccak(data)
    signable_message = encode_defunct(digest)
    signed_digest = w3.eth.account.sign_message(signable_message, private_key=adopter.private_key)
    signature = signed_digest.signature

    assert subscription.address == global_allow_list.feeModel()

    with ape.reverts("Only Access Controller can call this method"):
        subscription.beforeIsAuthorized(0, sender=adopter)

    with ape.reverts("Ritual must be active"):
        global_allow_list.isAuthorized(0, bytes(signature), bytes(data))

    erc20.approve(subscription.address, 10 * BASE_FEE, sender=adopter)
    subscription.payForSubscription(1, sender=adopter)
    coordinator.setRitual(
        ritual_id, RitualState.ACTIVE, 0, global_allow_list.address, sender=treasury
    )
    coordinator.processRitualPayment(adopter, ritual_id, MAX_NODES, DURATION, sender=treasury)
    global_allow_list.authorize(ritual_id, [adopter.address], sender=adopter)

    with ape.reverts("Ritual must be active"):
        global_allow_list.isAuthorized(0, bytes(signature), bytes(data))
    assert global_allow_list.isAuthorized(ritual_id, bytes(signature), bytes(data))

    end_subscription = subscription.getEndOfSubscription()
    chain.pending_timestamp = end_subscription + YELLOW_PERIOD + 2

    with ape.reverts("Yellow period has expired"):
        global_allow_list.isAuthorized(ritual_id, bytes(signature), bytes(data))

    subscription.payForSubscription(0, sender=adopter)
    assert global_allow_list.isAuthorized(ritual_id, bytes(signature), bytes(data))
