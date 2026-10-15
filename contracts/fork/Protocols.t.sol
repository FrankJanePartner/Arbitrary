// SPDX-License-Identifier: UNLICENSED
pragma solidity 0.8.30;
import {FlashArbitrageExecutor} from "../src/FlashArbitrageExecutor.sol";
import {Token} from "../test/Executor.t.sol";
import {IERC20} from "@openzeppelin/contracts/token/ERC20/IERC20.sol";
interface ForkVm {
 function envString(string calldata) external returns(string memory);
 function envAddress(string calldata) external returns(address);
 function envUint(string calldata) external returns(uint256);
 function createSelectFork(string calldata,uint256) external returns(uint256);
 function prank(address) external;
 function expectRevert() external;
}
interface Factory {function createPool(address,address,uint24) external returns(address);}
interface V3Pool {
 function initialize(uint160) external;
 function mint(address,int24,int24,uint128,bytes calldata) external returns(uint256,uint256);
}
/// Real Aave pool and Uniswap factory/router on a pinned fork.
/// Synthetic setup: impersonated aToken funding + new test token and deliberately skewed pools.
/// This is protocol compatibility evidence, never evidence of an available market profit.
contract ProtocolForkTest {
 ForkVm constant vm=ForkVm(address(uint160(uint256(keccak256("hevm cheat code")))));
 address loan; Token intermediate; address first;address second;FlashArbitrageExecutor e;
 address recipient=address(0xBEEF);address router;address pool;uint256 liquidity;
 function setUp() public {
  vm.createSelectFork(vm.envString("FORK_RPC"),vm.envUint("FORK_BLOCK"));
  loan=vm.envAddress("FORK_LOAN");router=vm.envAddress("FORK_ROUTER");pool=vm.envAddress("FORK_POOL");
  address atoken=vm.envAddress("FORK_ATOKEN");address factory=vm.envAddress("FORK_FACTORY");
  liquidity=IERC20(loan).balanceOf(atoken);
  require(liquidity>1e10,"not enough reserve for synthetic test funding");
  vm.prank(atoken);require(IERC20(loan).transfer(address(this),1e10));
  intermediate=new Token();intermediate.mint(address(this),1e12);
  first=Factory(factory).createPool(loan,address(intermediate),500);
  second=Factory(factory).createPool(loan,address(intermediate),3000);
  uint160 q=uint160(1<<96);
  V3Pool(first).initialize(loan<address(intermediate)?q*2:q/2);
  V3Pool(second).initialize(q);
  V3Pool(first).mint(address(this),-887220,887220,1e9,"");
  V3Pool(second).mint(address(this),-887220,887220,1e9,"");
  e=new FlashArbitrageExecutor(pool,address(this),address(this),recipient,address(0xCAFE),500);
  e.setToken(loan,true,true);e.setToken(address(intermediate),true,false);e.setRouter(router,2,true);
 }
 function uniswapV3MintCallback(uint256 a,uint256 b,bytes calldata) external {
  require(msg.sender==first||msg.sender==second);
  address token0=loan<address(intermediate)?loan:address(intermediate);
  address token1=loan<address(intermediate)?address(intermediate):loan;
  if(a>0)require(IERC20(token0).transfer(msg.sender,a));
  if(b>0)require(IERC20(token1).transfer(msg.sender,b));
 }
 function route() internal view returns(FlashArbitrageExecutor.Hop[] memory h){
  h=new FlashArbitrageExecutor.Hop[](2);
  h[0]=FlashArbitrageExecutor.Hop(2,router,loan,address(intermediate),500,1);
  h[1]=FlashArbitrageExecutor.Hop(2,router,address(intermediate),loan,3000,1);
 }
 function testRealLoanRouterRepaymentAndPayout() public {
  uint256 treasury=77;require(IERC20(loan).transfer(address(e),treasury));
  address atoken=vm.envAddress("FORK_ATOKEN");uint256 start=IERC20(loan).balanceOf(atoken);
  uint256 recipientBefore=IERC20(loan).balanceOf(recipient);
  e.execute(bytes32(uint256(1)),loan,1e6,route(),1,block.timestamp+30);
  require(IERC20(loan).balanceOf(recipient)>recipientBefore);require(IERC20(loan).balanceOf(address(e))==treasury);
  require(IERC20(loan).balanceOf(atoken)>=start);require(IERC20(loan).allowance(address(e),pool)==0);
 }
 function testUnprofitableRouteRevertsAtomically() public {
  address atoken=vm.envAddress("FORK_ATOKEN");uint256 start=IERC20(loan).balanceOf(atoken);
  uint256 recipientBefore=IERC20(loan).balanceOf(recipient);
  vm.expectRevert();e.execute(bytes32(uint256(2)),loan,1e6,route(),1e12,block.timestamp+30);
  require(IERC20(loan).balanceOf(atoken)==start);require(IERC20(loan).balanceOf(recipient)==recipientBefore);
  require(!e.usedIntents(bytes32(uint256(2))));
 }
}
