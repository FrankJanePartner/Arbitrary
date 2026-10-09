// SPDX-License-Identifier: UNLICENSED
pragma solidity 0.8.30;
import {IERC20} from "@openzeppelin/contracts/token/ERC20/IERC20.sol";
import {SafeERC20} from "@openzeppelin/contracts/token/ERC20/utils/SafeERC20.sol";
import {Ownable} from "@openzeppelin/contracts/access/Ownable.sol";
import {Ownable2Step} from "@openzeppelin/contracts/access/Ownable2Step.sol";
import {V2Adapter} from "./adapters/V2Adapter.sol";
import {V3Adapter} from "./adapters/V3Adapter.sol";
interface IAavePool {function flashLoanSimple(address,address,uint256,bytes calldata,uint16) external;}

/// @notice Same-chain, single-asset Aave flash-loan executor. No arbitrary calldata/delegatecall.
contract FlashArbitrageExecutor is Ownable2Step {
 using SafeERC20 for IERC20;
 struct Hop {uint8 kind;address router;address tokenIn;address tokenOut;uint24 fee;uint256 minOut;}
 address public immutable POOL;
 address public operator;
 address public recipient;
 bool public paused;
 mapping(address=>bool) public tokens;
 mapping(address=>bool) public loanAssets;
 mapping(address=>uint8) public routerKind; // 0 disabled, kind+1 enabled
 mapping(bytes32=>bool) public usedIntents;
 uint8 private phase; // 0 idle, 1 awaiting callback, 2 callback consumed
 bytes32 private context;
 error Invalid(); error Unauthorized(); error Unprofitable();
 event Executed(bytes32 indexed intentId,address indexed asset,address indexed recipient,uint256 amount,uint256 premium,uint256 profit,bytes32 routeHash);
 event ConfigurationChanged(bytes32 indexed kind,address indexed target,uint256 value);
 modifier idle(){if(phase!=0) revert Invalid();_;}
 constructor(address pool,address owner_,address operator_,address recipient_) Ownable(owner_) {
  if(pool.code.length==0 || operator_==address(0) || recipient_==address(0) || recipient_==address(this)) revert Invalid();
  POOL=pool;operator=operator_;recipient=recipient_;
 }
 function setOperator(address value) external onlyOwner idle {if(value==address(0))revert Invalid();operator=value;emit ConfigurationChanged("operator",value,0);}
 function setRecipient(address value) external onlyOwner idle {if(value==address(0)||value==address(this))revert Invalid();recipient=value;emit ConfigurationChanged("recipient",value,0);}
 function setPaused(bool value) external onlyOwner idle {paused=value;emit ConfigurationChanged("paused",address(0),value?1:0);}
 function setToken(address token,bool allowed,bool loan) external onlyOwner idle {if(token.code.length==0||(!allowed&&loan))revert Invalid();tokens[token]=allowed;loanAssets[token]=loan;emit ConfigurationChanged("token",token,allowed?1:0);}
 function setRouter(address router,uint8 kind,bool allowed) external onlyOwner idle {if(router.code.length==0||kind>2)revert Invalid();routerKind[router]=allowed?kind+1:0;emit ConfigurationChanged("router",router,allowed?kind+1:0);}
 function recover(address token,address to,uint256 amount) external onlyOwner idle {if(to==address(0))revert Invalid();IERC20(token).safeTransfer(to,amount);}
 function execute(bytes32 intentId,address asset,uint256 amount,Hop[] calldata route,uint256 minProfitToken,uint256 deadline) external idle {
  if(msg.sender!=operator)revert Unauthorized();
  if(paused||amount==0||intentId==bytes32(0)||usedIntents[intentId]||!loanAssets[asset]||deadline<block.timestamp||deadline>block.timestamp+120||route.length<2||route.length>3)revert Invalid();
  address previous=asset;
  for(uint256 i;i<route.length;i++){
   Hop calldata h=route[i];
   if(h.tokenIn!=previous||h.tokenIn==h.tokenOut||!tokens[h.tokenIn]||!tokens[h.tokenOut]||routerKind[h.router]!=h.kind+1||h.kind>2||h.minOut==0)revert Invalid();
   previous=h.tokenOut;
  }
  if(previous!=asset)revert Invalid();
  uint256 start=IERC20(asset).balanceOf(address(this));
  bytes memory params=abi.encode(intentId,asset,amount,route,minProfitToken,deadline,start);
  context=keccak256(params);usedIntents[intentId]=true;phase=1;
  IAavePool(POOL).flashLoanSimple(address(this),asset,amount,params,0);
  if(phase!=2 || IERC20(asset).balanceOf(address(this))<start)revert Invalid();
  IERC20(asset).forceApprove(POOL,0);context=bytes32(0);phase=0;
 }
 function executeOperation(address asset,uint256 amount,uint256 premium,address initiator,bytes calldata params) external returns(bool){
  if(msg.sender!=POOL||initiator!=address(this)||phase!=1||keccak256(params)!=context)revert Unauthorized();
  phase=2;
  (bytes32 intentId,address expectedAsset,uint256 expectedAmount,Hop[] memory route,uint256 minProfit,uint256 deadline,uint256 start)=abi.decode(params,(bytes32,address,uint256,Hop[],uint256,uint256,uint256));
  if(asset!=expectedAsset||amount!=expectedAmount||block.timestamp>deadline||IERC20(asset).balanceOf(address(this))!=start+amount)revert Invalid();
  uint256 current=amount;
  for(uint256 i;i<route.length;i++){
   Hop memory h=route[i];
   uint256 beforeOut=IERC20(h.tokenOut).balanceOf(address(this));
   uint256 beforeIn=IERC20(h.tokenIn).balanceOf(address(this));
   IERC20(h.tokenIn).forceApprove(h.router,current);
   if(h.kind==0)V2Adapter.swap(h.router,h.tokenIn,h.tokenOut,current,h.minOut,deadline);
   else V3Adapter.swap(h.kind,h.router,h.tokenIn,h.tokenOut,h.fee,current,h.minOut,deadline);
   IERC20(h.tokenIn).forceApprove(h.router,0);
   if(IERC20(h.tokenIn).balanceOf(address(this))!=beforeIn-current)revert Invalid();
   current=IERC20(h.tokenOut).balanceOf(address(this))-beforeOut;
   if(current<h.minOut)revert Invalid();
  }
  uint256 balance=IERC20(asset).balanceOf(address(this));
  if(balance<start+amount+premium+minProfit)revert Unprofitable();
  uint256 profit=balance-start-amount-premium;
  IERC20(asset).forceApprove(POOL,amount+premium);
  IERC20(asset).safeTransfer(recipient,profit);
  if(IERC20(asset).balanceOf(address(this))!=start+amount+premium)revert Invalid();
  emit Executed(intentId,asset,recipient,amount,premium,profit,keccak256(abi.encode(route)));
  return true;
 }
}
