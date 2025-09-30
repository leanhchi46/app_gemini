import MetaTrader5 as mt5
import time
from datetime import datetime, timedelta

def main():
    # Kết nối với MetaTrader 5
    if not mt5.initialize():
        print("initialize() failed, error code =", mt5.last_error())
        return

    print("Đã kết nối với MetaTrader 5")
    print("Phiên bản terminal:", mt5.terminal_info())
    print("Phiên bản thư viện:", mt5.version())

    # Lấy thông tin tài khoản
    account_info = mt5.account_info()
    if account_info is None:
        print("Không thể lấy thông tin tài khoản.")
        mt5.shutdown()
        return
    
    print(f"Đăng nhập vào tài khoản {account_info.login} trên server {account_info.server}")

    # Chuẩn bị yêu cầu đặt lệnh
    symbol = "XAUUSD"
    symbol_info = mt5.symbol_info(symbol)
    if symbol_info is None:
        print(symbol, "không tìm thấy, không thể gọi order_check()")
        mt5.shutdown()
        return

    if not symbol_info.visible:
        print(symbol, "is not visible, trying to switch on")
        if not mt5.symbol_select(symbol, True):
            print("symbol_select({}}) failed, exit", symbol)
            mt5.shutdown()
            return

    point = mt5.symbol_info(symbol).point
    price = mt5.symbol_info_tick(symbol).ask
    deviation = 20
    
    request = {
        "action": mt5.TRADE_ACTION_PENDING,
        "symbol": symbol,
        "volume": 0.01,
        "type": mt5.ORDER_TYPE_BUY_LIMIT,
        "price": price - 100 * point,
        "sl": price - 200 * point,
        "tp": price + 200 * point,
        "deviation": deviation,
        "magic": 234000,
        "comment": "python script open",
        "type_time": mt5.ORDER_TIME_GTC,
        "type_filling": mt5.ORDER_FILLING_IOC,
    }

    # Kiểm tra lệnh
    result = mt5.order_check(request)
    if result.retcode != mt5.TRADE_RETCODE_DONE:
        print("order_check failed, retcode={}".format(result.retcode))
        # In ra thông tin chi tiết hơn
        print("   result comment:", result.comment)
        print("   result balance:", result.balance)
        print("   result equity:", result.equity)
        print("   result margin:", result.margin)
        print("   result margin_free:", result.margin_free)
        print("   result margin_level:", result.margin_level)
    else:
        print("OrderCheck passed, sending order")
        # Gửi lệnh
        result = mt5.order_send(request)
        if result.retcode != mt5.TRADE_RETCODE_DONE:
            print("order_send failed, retcode={}".format(result.retcode))
            print("result", result)
        else:
            print("Lệnh đã được gửi thành công, ticket={}".format(result.order))

    # Ngắt kết nối
    mt5.shutdown()

if __name__ == '__main__':
    main()
