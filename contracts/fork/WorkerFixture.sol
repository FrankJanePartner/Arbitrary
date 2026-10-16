// SPDX-License-Identifier: UNLICENSED
pragma solidity 0.8.30;
import {Token} from "../test/Executor.t.sol";
import {IERC20} from "@openzeppelin/contracts/token/ERC20/IERC20.sol";
interface WorkerFactory {function createPool(address,address,uint24) external returns(address);}
interface WorkerPool {
 function initialize(uint160) external;
 function mint(address,int24,int24,uint128,bytes calldata) external returns(uint256,uint256);
}
/// Test-only liquidity fixture. Refuses every chain except local Anvil chain 31337.
contract WorkerFixture {
 address public immutable owner;
 address public immutable loan;
 Token public immutable intermediate;
 address public first;
 address public second;
 constructor(address asset) {
  require(block.chainid==31337,"local test chain only");
  owner=msg.sender;loan=asset;intermediate=new Token();
  intermediate.mint(address(this),1e12);
 }
 function seed(address factory) external {
  require(msg.sender==owner && first==address(0));
  first=WorkerFactory(factory).createPool(loan,address(intermediate),500);
  second=WorkerFactory(factory).createPool(loan,address(intermediate),3000);
  uint160 q=uint160(1<<96);
  WorkerPool(first).initialize(loan<address(intermediate)?q*2:q/2);
  WorkerPool(second).initialize(q);
  WorkerPool(first).mint(address(this),-887220,887220,1e9,"");
  WorkerPool(second).mint(address(this),-887220,887220,1e9,"");
 }
 function uniswapV3MintCallback(uint256 a,uint256 b,bytes calldata) external {
  require(msg.sender==first||msg.sender==second);
  address t0=loan<address(intermediate)?loan:address(intermediate);
  address t1=loan<address(intermediate)?address(intermediate):loan;
  if(a>0)require(IERC20(t0).transfer(msg.sender,a));
  if(b>0)require(IERC20(t1).transfer(msg.sender,b));
 }
}
