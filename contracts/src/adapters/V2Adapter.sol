// SPDX-License-Identifier: UNLICENSED
pragma solidity 0.8.30;
interface IV2Router {
 function swapExactTokensForTokens(uint256,uint256,address[] calldata,address,uint256) external returns(uint256[] memory);
}
library V2Adapter {
 function swap(address router,address input,address output,uint256 amount,uint256 minimum,uint256 deadline) internal {
  address[] memory path=new address[](2);path[0]=input;path[1]=output;
  IV2Router(router).swapExactTokensForTokens(amount,minimum,path,address(this),deadline);
 }
}
