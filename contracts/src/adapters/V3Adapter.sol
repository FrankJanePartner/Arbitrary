// SPDX-License-Identifier: UNLICENSED
pragma solidity 0.8.30;
interface IV3Router {
 struct Params {address tokenIn;address tokenOut;uint24 fee;address recipient;uint256 deadline;uint256 amountIn;uint256 amountOutMinimum;uint160 sqrtPriceLimitX96;}
 function exactInputSingle(Params calldata) external payable returns(uint256);
}
interface IV3Router02 {
 struct Params {address tokenIn;address tokenOut;uint24 fee;address recipient;uint256 amountIn;uint256 amountOutMinimum;uint160 sqrtPriceLimitX96;}
 function exactInputSingle(Params calldata) external payable returns(uint256);
}
library V3Adapter {
 function swap(uint8 kind,address router,address input,address output,uint24 fee,uint256 amount,uint256 minimum,uint256 deadline) internal {
  if(kind==1) IV3Router(router).exactInputSingle(IV3Router.Params(input,output,fee,address(this),deadline,amount,minimum,0));
  else IV3Router02(router).exactInputSingle(IV3Router02.Params(input,output,fee,address(this),amount,minimum,0));
 }
}
