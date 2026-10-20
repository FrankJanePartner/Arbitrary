// SPDX-License-Identifier: UNLICENSED
pragma solidity 0.8.30;
import {FlashArbitrageExecutor} from "../src/FlashArbitrageExecutor.sol";
import {Token} from "../test/Executor.t.sol";
import {IERC20} from "@openzeppelin/contracts/token/ERC20/IERC20.sol";

interface ForkV2Vm {
 function envString(string calldata) external returns(string memory);
 function envAddress(string calldata) external returns(address);
 function envUint(string calldata) external returns(uint256);
 function createSelectFork(string calldata,uint256) external returns(uint256);
 function prank(address) external;
 function expectRevert() external;
}
interface V2Factory {function createPair(address,address) external returns(address);}
interface V2Pair {function mint(address) external returns(uint256);}
interface V3Factory {function createPool(address,address,uint24) external returns(address);}
interface V3Pool {
 function initialize(uint160) external;
 function mint(address,int24,int24,uint128,bytes calldata) external returns(uint256,uint256);
}

/// Tests the standard Uniswap V2 Router02 adapter on a real Aave/V2/V3 fork.
/// Pools and relative prices are synthetic; this proves protocol execution only.
contract ProtocolV2ForkTest {
 ForkV2Vm constant vm=ForkV2Vm(address(uint160(uint256(keccak256("hevm cheat code")))));
 address loan; Token intermediate; address v2Pair; address v3Pool; FlashArbitrageExecutor executor;
 address recipient=address(0xBEEF); address v2Router; address v3Router; address lendingPool;
 function setUp() public {
  vm.createSelectFork(vm.envString("FORK_RPC"),vm.envUint("FORK_BLOCK"));
  loan=vm.envAddress("FORK_LOAN");
  lendingPool=vm.envAddress("FORK_POOL");
  v2Router=vm.envAddress("FORK_V2_ROUTER");
  v3Router=vm.envAddress("FORK_ROUTER");
  address atoken=vm.envAddress("FORK_ATOKEN");
  address v2Factory=vm.envAddress("FORK_V2_FACTORY");
  address v3Factory=vm.envAddress("FORK_FACTORY");

  vm.prank(atoken); require(IERC20(loan).transfer(address(this),1e12));
  intermediate=new Token();
  intermediate.mint(address(this),1e24);

  v2Pair=V2Factory(v2Factory).createPair(loan,address(intermediate));
  require(IERC20(loan).transfer(v2Pair,1e10));
  require(intermediate.transfer(v2Pair,1e22));
  V2Pair(v2Pair).mint(address(this));

  v3Pool=V3Factory(v3Factory).createPool(loan,address(intermediate),3000);
  uint160 q=uint160(1<<96);
  // V2 is seeded near parity in human token units; V3 gives the return leg
  // a deliberately favorable synthetic price to create a controlled profit.
  uint160 sqrtPrice=loan<address(intermediate)?q/500000:q*500000;
  V3Pool(v3Pool).initialize(sqrtPrice);
  V3Pool(v3Pool).mint(address(this),-887220,887220,1e16,"");

  executor=new FlashArbitrageExecutor(lendingPool,address(this),address(this),recipient,address(0xCAFE),500);
  executor.setToken(loan,true,true);
  executor.setToken(address(intermediate),true,false);
  executor.setRouter(v2Router,0,true);
  executor.setRouter(v3Router,2,true);
 }
 function uniswapV3MintCallback(uint256 a,uint256 b,bytes calldata) external {
  require(msg.sender==v3Pool);
  address token0=loan<address(intermediate)?loan:address(intermediate);
  address token1=loan<address(intermediate)?address(intermediate):loan;
  if(a>0) require(IERC20(token0).transfer(msg.sender,a));
  if(b>0) require(IERC20(token1).transfer(msg.sender,b));
 }
 function route() internal view returns(FlashArbitrageExecutor.Hop[] memory h) {
  h=new FlashArbitrageExecutor.Hop[](2);
  h[0]=FlashArbitrageExecutor.Hop(0,v2Router,loan,address(intermediate),0,1);
  h[1]=FlashArbitrageExecutor.Hop(2,v3Router,address(intermediate),loan,3000,1);
 }
 function testRealLoanV2V3RepaymentAndPayout() public {
  address atoken=vm.envAddress("FORK_ATOKEN");
  uint256 reserveBefore=IERC20(loan).balanceOf(atoken);
  uint256 recipientBefore=IERC20(loan).balanceOf(recipient);
  executor.execute(bytes32(uint256(1)),loan,1e6,route(),1,block.timestamp+30);
  require(IERC20(loan).balanceOf(recipient)>recipientBefore);
  require(IERC20(loan).balanceOf(atoken)>=reserveBefore);
  require(IERC20(loan).allowance(address(executor),lendingPool)==0);
 }
 function testUnprofitableV2V3RouteRevertsAtomically() public {
  address atoken=vm.envAddress("FORK_ATOKEN");
  uint256 reserveBefore=IERC20(loan).balanceOf(atoken);
  uint256 recipientBefore=IERC20(loan).balanceOf(recipient);
  vm.expectRevert();
  executor.execute(bytes32(uint256(2)),loan,1e6,route(),1e12,block.timestamp+30);
  require(IERC20(loan).balanceOf(atoken)==reserveBefore);
  require(IERC20(loan).balanceOf(recipient)==recipientBefore);
  require(!executor.usedIntents(bytes32(uint256(2))));
 }
}
