// SPDX-License-Identifier: UNLICENSED
pragma solidity 0.8.30;
import {FlashArbitrageExecutor} from "../src/FlashArbitrageExecutor.sol";
import {ERC20} from "@openzeppelin/contracts/token/ERC20/ERC20.sol";
interface Vm {function prank(address) external; function expectRevert() external; function warp(uint256) external;}
contract Token is ERC20 {constructor() ERC20("Test", "T") {} function mint(address a,uint256 n) external {_mint(a,n);}}
contract PoolMock {
 uint256 public premium=10;
 function flashLoanSimple(address receiver,address asset,uint256 amount,bytes calldata params,uint16) external {
  Token(asset).transfer(receiver,amount);
  require(FlashArbitrageExecutor(receiver).executeOperation(asset,amount,premium,receiver,params));
  Token(asset).transferFrom(receiver,address(this),amount+premium);
 }
}
contract RouterMock {
 uint256 public bonus;
 constructor(uint256 b){bonus=b;}
 function swapExactTokensForTokens(uint256 n,uint256 min,address[] calldata path,address to,uint256) external returns(uint256[] memory result){
  Token(path[0]).transferFrom(msg.sender,address(this),n);
  require(n+bonus>=min); Token(path[1]).transfer(to,n+bonus);
  result=new uint256[](2);result[0]=n;result[1]=n+bonus;
 }
}
contract ExecutorTest {
 Vm constant vm=Vm(address(uint160(uint256(keccak256("hevm cheat code")))));
 Token a;Token b;PoolMock pool;RouterMock r1;RouterMock r2;FlashArbitrageExecutor e;
 address recipient=address(0xBEEF);
 function setUp() public {
  a=new Token();b=new Token();pool=new PoolMock();r1=new RouterMock(0);r2=new RouterMock(100);
  e=new FlashArbitrageExecutor(address(pool),address(this),address(this),recipient);
  e.setToken(address(a),true,true);e.setToken(address(b),true,false);
  e.setRouter(address(r1),0,true);e.setRouter(address(r2),0,true);
  a.mint(address(pool),1e9);b.mint(address(r1),1e9);a.mint(address(r2),1e9);
 }
 function route() internal view returns(FlashArbitrageExecutor.Hop[] memory h){
  h=new FlashArbitrageExecutor.Hop[](2);
  h[0]=FlashArbitrageExecutor.Hop(0,address(r1),address(a),address(b),0,1);
  h[1]=FlashArbitrageExecutor.Hop(0,address(r2),address(b),address(a),0,1);
 }
 function go(bytes32 id,uint256 min) internal {e.execute(id,address(a),1000,route(),min,block.timestamp+20);}
 function testRepaysAndPaysOnlyIncrementalProfit() public {a.mint(address(e),77);go(bytes32(uint256(1)),50);require(a.balanceOf(recipient)==90);require(a.balanceOf(address(e))==77);require(a.balanceOf(address(pool))==1e9+10);require(a.allowance(address(e),address(pool))==0);}
 function testExistingBalanceCannotSubsidizeLoss() public {a.mint(address(e),10000);vm.expectRevert();go(bytes32(uint256(1)),91);}
 function testRejectsForgedCallback() public {vm.expectRevert();e.executeOperation(address(a),1000,10,address(e),"");}
 function testRejectsWrongInitiator() public {vm.prank(address(pool));vm.expectRevert();e.executeOperation(address(a),1000,10,address(1),"");}
 function testRejectsReplayAndReentrancy() public {go(bytes32(uint256(1)),50);vm.expectRevert();go(bytes32(uint256(1)),50);}
 function testRejectsUnknownRouter() public {e.setRouter(address(r1),0,false);vm.expectRevert();go(bytes32(uint256(1)),50);}
 function testOperatorCannotChangeRecipient() public {e.setOperator(address(123));vm.prank(address(123));vm.expectRevert();e.setRecipient(address(124));}
 function testPauseAndDeadline() public {e.setPaused(true);vm.expectRevert();go(bytes32(uint256(1)),50);e.setPaused(false);vm.expectRevert();e.execute(bytes32(uint256(2)),address(a),1000,route(),50,block.timestamp-1);}
 function testFuzzPreservesTreasury(uint96 start) public {a.mint(address(e),start);go(bytes32(uint256(1)),50);require(a.balanceOf(address(e))==start);require(a.balanceOf(recipient)==90);}
}
