from huobi_spot_client import Huobi_Spot_Client
import time
import numpy as np
import threading, logging
from chatrobot import DingtalkChatbot

# logging.basicConfig(filename='/home/ubuntu/logs/Double_EMA_SigControl_ETHUSD_frankcao.log',
#                     level=logging.INFO,format='%(asctime)s - %(levelname)s - %(module)s - %(message)s')
# logging.basicConfig(filename='E:/Alaric_工作最新/Alaric/BlackPulse/策略研究/grid_backtrader_test/实盘/grid_strategy_test.log',
#                     level=logging.INFO,format='%(asctime)s - %(levelname)s - %(module)s - %(message)s')
logger = logging.getLogger('root')

apiKey = 'rfhfg2mkl3-e3652fe2-4cd0ea14-46c88'
secret = '83b02bf0-324313d3-6e0f1e3a-7b6d9'


is_proxies = False

target_coin = 'btc'
base_coin = 'usdt'
trade_symbol = 'btcusdt'

price_decimal = 2
amount_decimal = 6

class Grid_long_stoptrail():

    def __init__(self):
        # 策略信息
        self.xiaoding = DingtalkChatbot('https://oapi.dingtalk.com/robot/send?access_token=c9f78b83765fd7ce05b9a080a1d990e411721a0e00dbc715ac25436cd63e0b4e')
        self.strategy_name = '火币网格风险中性策略测试'

        # 策略所需参数
        self.stoptrail_triger_percent = 1.006
        self.stoptrail_space = 0.003

        # 实例化交易所接口
        self.huobi_spot_client = Huobi_Spot_Client(Access_Key=apiKey, Secret_Key=secret, is_proxies = is_proxies)

        # 账户信息(初始）
        self.initial_target_coin_trade = 0
        self.initial_target_coin_frozen = 0
        self.initial_total_target_coin = 0
        self.initial_base_coin_trade = 0
        self.initial_base_coin_frozen = 0
        self.initial_total_base_coin = 0
        # 当前账户信息
        self.current_target_coin_trade = 0
        self.current_target_coin_frozen = 0
        self.current_total_target_coin = 0
        self.current_base_coin_trade = 0
        self.current_base_coin_frozen = 0
        self.current_total_base_coin = 0
        # 价格信息
        self.current_price = 0
        # 更新价格信息，用来判断追踪止损
        self.new_price = 0
        self.last_price = 0

        # 记录每个循环开始时候的时间戳
        self.start_timestamp = 0

        # 订单信息
        self.stoptrail_order_id = None

        # 追踪止损控制器
        self.stop_trial_ing = False

        # 计算平均价格所需参数
        self.average_cost = None

        # renew price thread
        self.renew_price_thread = None

        # 记录时间戳
        self.current_hour = time.localtime(time.time()).tm_hour
        self.last_hour = 0

        # 记录last usdt position
        self.last_avg_cost = 0

        # 记录止盈订单的order id
        self.stop_profit_order_id = None



        self.start_check()
        self.get_initial_position()
        message = '策略 %s 初始化 \n初始的目标标的可用量: %s \n初始的目标标的冻结量: %s \n初始的目标标的总量: %s' \
                  '\n初始的USDT可用量: %s \n初始的USDT冻结量: %s \n初始的USDT总量: %s \n当地时间：%s' \
                  % (self.strategy_name,self.format_amount(self.initial_target_coin_trade),
                     self.format_amount(self.initial_target_coin_frozen),self.format_amount(self.initial_total_target_coin),
                     self.format_amount(self.initial_base_coin_trade),self.format_amount(self.initial_base_coin_frozen),
                     self.format_amount(self.initial_total_base_coin),time.strftime("%Y-%m-%d %H:%M:%S", time.localtime()))
        # logger.info(message)
        self.dingding_notice(message)

    # 用来做初始化检查，取消所有的订单，并且在有仓位的情况下清掉所有的仓位
    def start_check(self):
        self.cancel_order_all()
        time.sleep(2)
        self.get_current_position()
        # 用来判断是否处于check position的状态，用于在下完市价单卖出已有仓位后，要check仓位是否归零，在仓位归零后break掉while循环
        position_check = False

        while True:
            # 当position check处于False状态下的时候，检查仓位是否为0
            if position_check == False:
                # 如果仓位不为0，则卖点所有仓位，使仓位归零
                if self.current_target_coin_trade > 0.000002:
                    trade_amount = self.current_target_coin_trade
                    message = 'Initial target coin position is not 0, clean position, trade amount is %s' % (trade_amount)
                    print(message)
                    # aa = self.huobi_spot_client.create_order(symbol=trade_symbol, type='market', side='sell',amount=self.format_amount(trade_amount))
                    aa = self.huobi_spot_client.create_order(symbol=trade_symbol, type='sell-market',amount=str(self.format_amount(trade_amount)))
                    position_check = True
                # 如果仓位本来就是0，则break掉循环，check程序结束
                else:
                    break

            # 已经下了实价卖出订单，开始不停地check position，当仓位归零后break掉循环，并结束
            elif position_check == True:
                self.get_current_position()
                # 仓位归零并结束
                if self.format_amount(self.current_total_target_coin) <= 0.000002:
                    message = 'Clean position finished, position size is 0, ready to start!'
                    print(message)
                    # logging.info(message)
                    self.dingding_notice(message)
                    break
                # 仓位不是零，1s后再次检查
                else:
                    message = 'Clean position finished, but postion is not 0, wait 1 second and clean it again'
                    print(message)
                    # logging.info(message)
                    self.dingding_notice(message)
            time.sleep(1)
    # 钉钉推送线程
    def ding_thread(self, out):
        self.xiaoding.send_text(out, is_at_all=False)
    # 钉钉推送，使用线程，防止卡死导致主程序断掉
    def dingding_notice(self, message=None):
        self.get_current_position()
        basic_info = '\n --------------------------------\nStrategy: test %s \nSymbol: %s' \
                     '\nTarget coin Position: %s \nBase coin Position: %s\nLocal time: %s\n --------------------------------\n' \
                    % (self.strategy_name,trade_symbol,self.format_amount(self.current_total_target_coin),self.format_amount(self.current_total_base_coin),time.strftime("%Y-%m-%d %H:%M:%S", time.localtime()))
        out = message + basic_info
        t = threading.Thread(target=self.ding_thread, args=(out,),)
        t.start()
    # 获取初始仓位
    def get_initial_position(self):
        data = self.huobi_spot_client.get_account_balance()['data']['list']
        for i in range(len(data)):
            if data[i]['currency'] == target_coin and data[i]['type'] == 'trade':
                self.initial_target_coin_trade = float(data[i]['balance'])
            if data[i]['currency'] == target_coin and data[i]['type'] == 'frozen':
                self.initial_target_coin_frozen = float(data[i]['balance'])

            if data[i]['currency'] == base_coin and data[i]['type'] == 'trade':
                self.initial_base_coin_trade = float(data[i]['balance'])
            if data[i]['currency'] == base_coin and data[i]['type'] == 'frozen':
                self.initial_base_coin_frozen = float(data[i]['balance'])
        self.initial_total_target_coin = self.initial_target_coin_trade + self.initial_target_coin_frozen
        self.initial_total_base_coin = self.initial_base_coin_trade + self.initial_base_coin_frozen
        # print('初始的目标标的可用量',self.format_amount(self.initial_target_coin_trade))
        # print('初始的目标标的冻结量',self.format_amount(self.initial_target_coin_frozen))
        # print('初始的目标标的总量',self.format_amount(self.initial_total_target_coin))
        # print('初始的USDT可用量',self.format_amount(self.initial_base_coin_trade))
        # print('初始的USDT冻结量',self.format_amount(self.initial_base_coin_frozen))
        # print('初始的USDT总量',self.format_amount(self.initial_total_base_coin))
    # 获取最新仓位
    def get_current_position(self):
        data = self.huobi_spot_client.get_account_balance()['data']['list']
        for i in range(len(data)):
            if data[i]['currency'] == target_coin and data[i]['type'] == 'trade':
                self.current_target_coin_trade = float(data[i]['balance'])
            if data[i]['currency'] == target_coin and data[i]['type'] == 'frozen':
                self.current_target_coin_frozen = float(data[i]['balance'])

            if data[i]['currency'] == base_coin and data[i]['type'] == 'trade':
                self.current_base_coin_trade = float(data[i]['balance'])
            if data[i]['currency'] == base_coin and data[i]['type'] == 'frozen':
                self.current_base_coin_frozen = float(data[i]['balance'])

        self.current_total_target_coin = self.current_target_coin_trade + self.current_target_coin_frozen
        self.current_total_base_coin = self.current_base_coin_trade + self.current_base_coin_frozen
        # print(self.current_target_coin_trade)
        # print(self.current_target_coin_frozen)
        # print(self.current_total_target_coin)
        # print(self.current_base_coin_trade)
        # print(self.current_base_coin_frozen)
        # print(self.current_total_base_coin)
    # 获取最新市场价格
    def get_current_market_price(self):
        self.current_price = self.huobi_spot_client.get_ticker(symbol=trade_symbol)['tick']['close']
        # print(self.current_price)
        return self.current_price
    # 标准化价格后的小数点位数
    def format_price(self,coin_price):
        price = round(coin_price,price_decimal)
        return price
    # 标准化交易数量的小数点位数
    def format_amount(self,coin_amount):
        # 由于使用四舍五入进一位可能会导致市价止损仓位不够无法卖出，所以采取舍去法
        amount = int(coin_amount * 10**amount_decimal)/(10**amount_decimal)
        # amount = round(coin_amount,amount_decimal)
        return amount
    # 下网格单
    def palce_orders(self):
        self.get_current_market_price()
        self.get_current_position()

        # 计算每份交易使用的仓位
        first_amount = self.current_base_coin_trade / 258

        # 列出网格下单价格
        grid_price = [self.current_price * 0.999363958, self.current_price * 0.994770318,
                      self.current_price * 0.978869258, self.current_price * 0.932508834,
                      self.current_price * 0.889964664, self.current_price * 0.856537102,
                      self.current_price * 0.836042403, self.current_price * 0.814204947,
                      self.current_price * 0.794204947, self.current_price * 0.763214542]
        # 先下一个市价单买入最小仓位
        self.huobi_spot_client.create_order(symbol=trade_symbol, type='buy-market', amount='6')
        # 由于火币市价单成交速度比较慢，所以sleep 10s等待成交
        time.sleep(10)
        # 下剩下的限价网格单
        self.huobi_spot_client.create_order(symbol=trade_symbol, type='buy-limit',
                                            price=str(self.format_price(grid_price[0])),
                                            amount=str(self.format_amount(first_amount / grid_price[0] * 1)))
        self.huobi_spot_client.create_order(symbol=trade_symbol, type='buy-limit',
                                            price=str(self.format_price(grid_price[1])),
                                            amount=str(self.format_amount(first_amount / grid_price[1] * 1)))
        self.huobi_spot_client.create_order(symbol=trade_symbol, type='buy-limit',
                                            price=str(self.format_price(grid_price[2])),
                                            amount=str(self.format_amount(first_amount / grid_price[2] * 2)))
        self.huobi_spot_client.create_order(symbol=trade_symbol, type='buy-limit',
                                            price=str(self.format_price(grid_price[3])),
                                            amount=str(self.format_amount(first_amount / grid_price[3] * 2)))
        self.huobi_spot_client.create_order(symbol=trade_symbol, type='buy-limit',
                                            price=str(self.format_price(grid_price[4])),
                                            amount=str(self.format_amount(first_amount / grid_price[4] * 4)))
        self.huobi_spot_client.create_order(symbol=trade_symbol, type='buy-limit',
                                            price=str(self.format_price(grid_price[5])),
                                            amount=str(self.format_amount(first_amount / grid_price[5] * 8)))
        self.huobi_spot_client.create_order(symbol=trade_symbol, type='buy-limit',
                                            price=str(self.format_price(grid_price[6])),
                                            amount=str(self.format_amount(first_amount / grid_price[6] * 16)))
        self.huobi_spot_client.create_order(symbol=trade_symbol, type='buy-limit',
                                            price=str(self.format_price(grid_price[7])),
                                            amount=str(self.format_amount(first_amount / grid_price[7] * 32)))
        self.huobi_spot_client.create_order(symbol=trade_symbol, type='buy-limit',
                                            price=str(self.format_price(grid_price[8])),
                                            amount=str(self.format_amount(first_amount / grid_price[8] * 64)))
        self.huobi_spot_client.create_order(symbol=trade_symbol, type='buy-limit',
                                            price=str(self.format_price(grid_price[9])),
                                            amount=str(self.format_amount(first_amount / grid_price[9] * 126)))

    # 计算从每个循环开始后的持仓均价
    def cal_avg_cost(self):
        total_cost = 0
        total_amount = 0
        # 计算所有完全成交订单的总费用和总数量
        aa = self.huobi_spot_client.get_history_orders(symbol=trade_symbol, state='filled',start_time=self.start_timestamp)
        if aa['status']=='ok' and len(aa['data']) != 0:
            for i in range(len(aa['data'])):
                total_cost += float(aa['data'][i]['field-cash-amount'])
                total_amount += float(aa['data'][i]['field-amount'])-float(aa['data'][i]['field-fees'])
        else:
            message = 'cannot get history filled order or there are no history filled order'
            # self.dingding_notice(message)
            # print(message)
        # 计算所有部分成交订单的总费用和总数量
        bb = self.huobi_spot_client.get_history_orders(symbol=trade_symbol, state='partial-filled',start_time=self.start_timestamp)
        if bb['status']=='ok' and len(bb['data']) != 0:
            for j in range(len(bb['data'])):
                total_cost += float(bb['data'][j]['field-cash-amount'])
                total_amount += float(bb['data'][j]['field-amount'])-float(aa['data'][j]['field-fees'])
        else:
            message = 'cannot get history partial-filled order or there are no history partial-filled order'
            # self.dingding_notice(message)
            # print(message)
        if total_cost != 0 and total_amount != 0:
            self.average_cost  = total_cost / total_amount
        else:
            print('amount or cost is 0')
    # 每隔一段时间刷新一下最新价格
    def renew_price(self,renew_period = 5):
        self.new_price = self.huobi_spot_client.get_ticker(symbol=trade_symbol)['tick']['close']
        while True:
            self.last_price = self.new_price
            self.new_price = self.huobi_spot_client.get_ticker(symbol=trade_symbol)['tick']['close']
            # print('Time',time.strftime("%Y-%m-%d %H:%M:%S", time.localtime()),'last price is ', self.last_price)
            # print('Time',time.strftime("%Y-%m-%d %H:%M:%S", time.localtime()),'new price is ',self.new_price)
            time.sleep(renew_period)

    # 调用接口取消所有订单
    def cancel_order_all(self):
        aa = self.huobi_spot_client.cancel_order_all(symbol=trade_symbol)

    def run(self):
        while True:
            # 记录时间戳
            self.current_hour = time.localtime(time.time()).tm_hour

            # 用线程获取最新的仓位信息
            get_postition_thread = threading.Thread(target=self.get_current_position)
            get_postition_thread.start()
            while get_postition_thread.is_alive() is True:
                time.sleep(0.5)
            time.sleep(1.5)
            # print('target coin amount',self.current_total_target_coin)

            if self.current_hour != self.last_hour:
                message = 'Main thread running normal, current total target coin position is %s' %(self.current_total_target_coin)
                self.dingding_notice(message)
                print(message)

            # 如果仓位为0，则开始新的循环
            if self.format_amount(self.current_total_target_coin) <= 0.000002:
                # 记录循环初始的时间戳
                self.start_timestamp = int(round(time.time() * 1000))
                # cancal_order_thread = threading.Thread(target=self.cancel_order_all)
                # cancal_order_thread.start()
                aa = self.cancel_order_all()
                message = 'new circle started, cancel all order'
                print(message)
                # 下网格单
                self.palce_orders()
                # 把last position设为0 这样下一个循环就会下止盈单
                self.last_avg_cost = 0

                # self.stop_trial_ing = False
                message = 'position is 0, create grid order'
                print(message)
                # logging.info(message)
                self.dingding_notice(message)
                # time.sleep(1800)

                # 如果进入新的循环，更新一下初始化的position
                get_initial_postition_thread = threading.Thread(target=self.get_initial_position)
                get_initial_postition_thread.start()
                while get_initial_postition_thread.is_alive() is True:
                    time.sleep(0.5)
            # 如果仓位大于0，则判断是否出发追踪止损
            elif self.format_amount(self.current_total_target_coin) > 0.000002:
                # 计算平均价格，因为可能卡死，所以使用线程
                avg_cost_thread = threading.Thread(target=self.cal_avg_cost)
                avg_cost_thread.start()
                while avg_cost_thread.is_alive() is True:
                    time.sleep(0.5)
                if self.average_cost != None:
                    avg_cost = self.average_cost
                else:
                    avg_cost = self.cal_avg_cost()

                position_ratio = (self.initial_total_base_coin-self.current_total_base_coin)/self.initial_total_base_coin
                if position_ratio < 0.01:
                    self.stoptrail_triger_percent = 1.05
                elif position_ratio < 0.05:
                    self.stoptrail_triger_percent = 1.025
                elif position_ratio < 0.1:
                    self.stoptrail_triger_percent = 1.02
                elif position_ratio < 0.15:
                    self.stoptrail_triger_percent = 1.015
                else:
                    self.stoptrail_triger_percent = 1.01

                trigger_point = avg_cost * self.stoptrail_triger_percent

                if self.current_hour != self.last_hour:
                    message = 'Time: %s, average cost is: %s, stoptrail triger point is: %s. ' \
                              % (time.strftime("%Y-%m-%d %H:%M:%S"), avg_cost, trigger_point)
                    self.dingding_notice(message)
                    print(message)

                if avg_cost != self.last_avg_cost:
                    message = 'Time: %s. Position changed, last avg cost is %s, current avg cost is %s'%\
                              (time.strftime("%Y-%m-%d %H:%M:%S"),self.last_avg_cost,avg_cost)
                    self.dingding_notice(message)
                    print(message)
                    if self.stop_profit_order_id == None:
                        aa = self.huobi_spot_client.create_order(symbol=trade_symbol, type='sell-limit',price=str(self.format_price(trigger_point)),
                                                            amount=str(self.format_amount(self.current_target_coin_trade)))
                        self.stop_profit_order_id = str(aa['data'])
                        message = 'Time: %s. There is no stop profit order, create stop profit order, the price is %s, and the amount is %s' \
                                  %(time.strftime("%Y-%m-%d %H:%M:%S"),self.format_price(trigger_point),self.format_amount(self.current_target_coin_trade))
                        self.dingding_notice(message)
                        print(message)
                    else:
                        self.huobi_spot_client.cancel_order_by_id(order_id=self.stop_profit_order_id)
                        time.sleep(2)
                        self.get_current_position()
                        time.sleep(2)
                        aa = self.huobi_spot_client.create_order(symbol=trade_symbol, type='sell-limit',price=str(self.format_price(trigger_point)),
                                                            amount=str(self.format_amount(self.current_target_coin_trade)))
                        self.stop_profit_order_id = str(aa['data'])
                        message = 'Time: %s, average cost changed, cancel previous stop profit order and create new one, the price is %s, and the amount is %s'\
                                  %(time.strftime("%Y-%m-%d %H:%M:%S"),self.format_price(trigger_point),self.format_amount(self.current_target_coin_trade))
                        self.dingding_notice(message)
                        print(message)

                    self.last_avg_cost = avg_cost

            self.last_hour = self.current_hour

            time.sleep(3)


aa=Grid_long_stoptrail()
# aa.cal_avg_cost()
# aa.get_initial_position()
# aa.get_current_position()
# print(aa.get_current_market_price())
# aa.renew_price()
# aa.palce_orders()
# print(aa.cancel_order_all())
aa.run()
# aa.dingding_notice('网格策略测试')
# trade_amount = aa.current_target_coin_trade
# print('trade amount is ',trade_amount)
# bb = aa.huobi_spot_client.create_order(symbol=trade_symbol, type='market', side='sell',amount=aa.format_amount(trade_amount))
# print(bb)
