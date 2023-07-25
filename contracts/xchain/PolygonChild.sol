// SPDX-License-Identifier: MIT
pragma solidity ^0.8.0;

import "@fx-portal/contracts/tunnel/FxBaseChildTunnel.sol";

contract PolygonChild is FxBaseChildTunnel {

    address public immutable stakeInfo;
    
    constructor(
        address _fxChild,
        address _stakeInfo
    ) FxBaseChildTunnel(_fxChild) {
        stakeInfo = _stakeInfo;
    }

    function _processMessageFromRoot(
        uint256 /* stateId */,
        address sender,
        bytes memory data
    ) internal override validateSender(sender) {
        (bool success, /* returnId */ ) = stakeInfo.call(data);
    }

}