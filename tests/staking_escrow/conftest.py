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

import pytest
import ape
from web3 import Web3

TOTAL_SUPPLY = Web3.to_wei(1_000_000_000, "ether")  # TODO NU(1_000_000_000, 'NU').to_units()


@pytest.fixture()
def token(project, accounts):
    return accounts[0].deploy(project.NuCypherToken, TOTAL_SUPPLY)


@pytest.fixture()
def worklock(project, token, accounts):
    return accounts[0].deploy(project.WorkLockForStakingEscrowMock, token.address)


@pytest.fixture()
def threshold_staking(project, accounts):
    return accounts[0].deploy(project.ThresholdStakingForStakingEscrowMock)


@pytest.fixture(params=[False, True])
def escrow(project, token, worklock, threshold_staking, request, accounts):
    creator = accounts[0]
    contract = creator.deploy(
        project.EnhancedStakingEscrow, token.address, worklock.address, threshold_staking.address
    )

    if request.param:
        dispatcher = creator.deploy(project.Dispatcher, contract.address)
        contract = project.EnhancedStakingEscrow.at(dispatcher.address)

    worklock.setStakingEscrow(contract.address, sender=creator)
    threshold_staking.setStakingEscrow(contract.address, sender=creator)

    assert contract.token() == token.address
    assert contract.workLock() == worklock.address

    return contract
