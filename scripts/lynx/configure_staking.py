from ape import networks, project
from ape.api import AccountAPI
from ape.cli import get_user_selected_account
from deployment.constants import ARTIFACTS_DIR
from deployment.registry import contracts_from_registry

ROOT_REGISTRY_FILEPATH = ARTIFACTS_DIR / "lynx" / "lynx-alpha-13-root-registry.json"
CHILD_REGISTRY_FILEPATH = ARTIFACTS_DIR / "lynx" / "lynx-alpha-13-child-registry.json"

LYNX_NODES = {
    # staking provider -> operator
    "0xb15d5a4e2be34f4be154a1b08a94ab920ffd8a41": "0x890069745E9497C6f99Db68C4588deC5669F3d3E",
    "0x210eeac07542f815ebb6fd6689637d8ca2689392": "0xf48F720A2Ed237c24F5A7686543D90596bb8D44D",
    "0x48C8039c32F4c6f5cb206A5911C8Ae814929C16B": "0xce057adc39dcD1b3eA28661194E8963481CC48b2",
}


def configure_goerli_root(deployer_account: AccountAPI) -> int:
    """Configures ThresholdStaking and TACoApplication on Goerli."""
    deployments = contracts_from_registry(filepath=ROOT_REGISTRY_FILEPATH)

    # Set up lynx stakes on Goerli
    eth_network = networks.ethereum.goerli
    with eth_network.use_provider("infura"):
        taco_application_contract = deployments[project.TACoApplication.contract_type.name]
        threshold_staking_contract = deployments[project.TestnetThresholdStaking.contract_type.name]

        min_stake_size = taco_application_contract.minimumAuthorization()
        for staking_provider, operator in LYNX_NODES.items():
            # staking
            print(f"Setting roles for staking provider {staking_provider} on Goerli")
            threshold_staking_contract.setRoles(
                staking_provider,
                deployer_account.address,
                staking_provider,
                staking_provider,
                sender=deployer_account,
            )

            print(
                f"Authorizing increased in stake for staking provider {staking_provider} on Goerli"
            )
            threshold_staking_contract.authorizationIncreased(
                staking_provider, 0, min_stake_size, sender=deployer_account
            )

            # bonding
            print(f"Bonding operator {operator} for {staking_provider} on Goerli")
            taco_application_contract.bondOperator(
                staking_provider, operator, sender=deployer_account
            )

    return min_stake_size


def configure_mumbai_root(deployer_account: AccountAPI, stake_size: int):
    """Configures MockTACoApplication on Mumbai."""
    deployments = contracts_from_registry(filepath=CHILD_REGISTRY_FILEPATH)

    # Set up lynx stakes on Mumbai
    poly_network = networks.polygon.mumbai
    with poly_network.use_provider("infura"):
        mock_taco_application_contract = deployments[
            project.LynxMockTACoApplication.contract_type.name
        ]

        for staking_provider, operator in LYNX_NODES.items():
            # staking
            print(f"Setting stake for staking provider {staking_provider} on Mumbai")
            mock_taco_application_contract.updateAuthorization(
                staking_provider, stake_size, sender=deployer_account
            )

            # bonding
            print(f"Bonding operator {operator} for {staking_provider} on Mumbai")
            mock_taco_application_contract.updateOperator(
                staking_provider, operator, sender=deployer_account
            )


def main():
    deployer_account = get_user_selected_account()
    stake_size = configure_goerli_root(deployer_account)
    configure_mumbai_root(deployer_account, stake_size)
