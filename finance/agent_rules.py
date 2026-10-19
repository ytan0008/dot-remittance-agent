"""Offline rule planner used when no model is configured. It is labeled as such and is not an AI model.

It follows the same understand -> plan -> act pipeline and the same tools, so guardrails behave identically.
"""
import json
import re
from decimal import Decimal
from .domain import canonical
from .student import money

KEYWORDS = {
    "forget": ["forget", "忘记", "忘記", "忘掉", "quên", "忘れて", "잊어"],
    "recall": ["what do you remember", "do you remember", "你记得", "你記得", "记得什么", "記得什麼", "bạn nhớ", "覚えてる",
               "覚えている", "기억나", "기억하고"],
    "remember": ["remember", "记住", "記住", "ghi nhớ", "覚えて", "기억해"],
    "timing": ["good time to exchange", "when should i exchange", "when to exchange", "should i exchange", "exchange now",
               "什么时候换汇", "现在换汇", "该不该换汇", "适合换汇", "什麼時候換匯", "現在換匯", "適合換匯", "khi nào nên đổi",
               "có nên đổi", "đổi tiền lúc nào", "両替のタイミング", "今両替", "いつ両替", "환전 타이밍", "지금 환전", "언제 환전"],
    "progress": ["badge", "streak", "challenge", "my progress", "徽章", "勋章", "連續", "连续打卡", "挑战", "挑戰", "成就", "huy hiệu",
                 "chuỗi ngày", "thử thách", "バッジ", "連続", "チャレンジ", "배지", "연속", "챌린지"],
    "afford": ["afford", "can i buy", "should i buy", "买得起", "能不能买", "可以买吗", "该不该买", "買得起", "能不能買", "可以買嗎",
               "có đủ tiền", "mua được không", "có nên mua", "買える", "買っても", "살 수 있", "사도 될까", "감당"],
    "scholarship": ["scholarship", "grant", "bursary", "奖学金", "獎學金", "助学金", "助學金", "học bổng", "奨学金", "給付金", "장학금"],
    "cashflow": ["cash flow", "cashflow", "semester", "term plan", "现金流", "現金流", "学期", "學期", "dòng tiền", "học kỳ",
                 "キャッシュフロー", "학기", "현금 흐름"],
    "insights": ["insight", "how am i doing", "spending report", "tips", "总结", "小结", "建议", "總結", "建議", "tổng kết", "gợi ý",
                 "まとめ", "アドバイス", "요약", "조언"],
    "execute": ["execute", "submit", "pay now", "go ahead and send", "执行", "執行", "提交", "thực hiện", "実行", "送信して", "실행", "제출"],
    "track": ["status", "track", "reconcile", "到账", "到賬", "状态", "狀態", "进度", "進度", "trạng thái", "状況", "상태"],
    "forecast": ["forecast", "predict", "预测", "預測", "dự báo", "予測", "예측"],
    "scenario": ["scenario", "what if", "if the rate", "情景", "如果", "假如", "nếu", "もし", "만약"],
    "compare": ["compare", "cheapest", "best option", "options", "比较", "比較", "方案", "划算", "划算", "so sánh", "비교", "最安"],
    "rates": ["rate", "exchange", "汇率", "匯率", "tỷ giá", "レート", "為替", "환율"],
    "prepare": ["send", "transfer", "remit", "pay ", "汇款", "匯款", "转账", "轉帳", "付款", "支付", "gửi", "chuyển",
                "送金", "振込", "송금", "보내", "이체"],
    "balance": ["balance", "funds", "how much do i have", "余额", "餘額", "资金", "資金", "số dư", "残高", "잔액"],
    "expense": ["spent", "expense", "log ", "记账", "记一笔", "記帳", "花了", "chi tiêu", "使った", "썼어", "지출"],
    "reminders": ["remind", "deadline", "due", "提醒", "截止", "到期", "nhắc", "hạn", "リマインド", "期限", "알림", "마감"],
    "goals": ["goal", "budget", "plan", "目标", "目標", "预算", "預算", "mục tiêu", "ngân sách", "目標", "予算", "목표", "예산"],
    "credit": ["credit", "habit", "信用", "习惯", "習慣", "tín dụng", "thói quen", "クレジット", "신용"],
}
CURRENCY_WORDS = {
    "AUD": ["aud", "澳元", "澳币", "澳幣", "đô úc", "豪ドル", "호주 달러"],
    "USD": ["usd", "美元", "美金", "đô la mỹ", "ドル", "달러"],
    "CNY": ["cny", "rmb", "人民币", "人民幣", "nhân dân tệ", "人民元", "위안"],
    "VND": ["vnd", "越南盾", "đồng", "ベトナムドン", "베트남 동"],
    "PHP": ["php", "菲律宾比索", "比索", "peso"],
    "MXN": ["mxn"], "JPY": ["jpy", "日元", "日圓", "円", "엔화"], "KRW": ["krw", "韩元", "韓元", "ウォン", "원화"],
    "HKD": ["hkd", "港币", "港幣"], "TWD": ["twd", "新台币", "新台幣"], "SGD": ["sgd"], "NZD": ["nzd"], "CAD": ["cad"],
    "EUR": ["eur", "欧元", "歐元"], "ETH": ["eth", "以太"],
}
PURPOSE = [r"用途[:：是为]*(.{2,40})", r"mục đích[:：]?\s*(.{3,60})", r"目的[:：]\s*(.{2,40})", r"용도[:：]?\s*(.{2,40})",
           r"\bfor\s+(.{3,80})$", r"用于(.{2,40})", r"用於(.{2,40})", r"作为(.{2,40})", r"作為(.{2,40})",
           r"để\s+(.{3,60})", r"の(.{2,20})のため", r"([^\sにへをで]{1,20})として"]
# Names of people not yet registered, used only to prefill the recipient form.
NEW_NAME = [r"(?:给|給)\s*([^\s，,。用让讓的]{1,20}?)\s*(?:汇|匯|转|轉|寄|付)", r"\bto\s+([A-Z][\w-]{0,30})", r"\bcho\s+([^\s,.]{1,30})",
            r"([^\s、,。]{1,20})\s*(?:に|へ)\s*(?:送金|送る|振込)", r"([^\s,]{1,20})에게"]
RECEIVE = ["receives", "receive", "gets", "收到", "到账", "到賬", "nhận", "受け取", "받게", "받도록", "수령"]
WEEK = ["week", "周", "週", "tuần", "주"]
ROUTINE = ["every", "monthly", "weekly", "usually", "each month", "每月", "每个月", "每個月", "每周", "通常", "hàng tháng", "mỗi tháng",
           "毎月", "毎週", "매달", "매월", "매주"]
PREFER = ["prefer", "喜欢", "喜歡", "偏好", "thích", "好み", "선호"]
DOWN = ["less favorable", "worse", "drop", "fall", "down", "lower", "下跌", "下降", "贬", "貶", "不利", "跌", "giảm", "下落", "下が",
        "하락", "떨어"]

TEXT = {
    "en": dict(adv_good_time='AI watch: {pair} looks like a good time to exchange — {rate}, better than {p}% of the last 90 days.', adv_wait='AI watch: {pair} is low for the last 90 days (better than only {p}%); if you can wait, waiting looks reasonable.', adv_deadline='AI watch: your deadline is close — exchange {pair} soon rather than wait (now {rate}).', adv_below_floor='AI watch: {pair} is {rate}, below the rate you said is acceptable; I will remind you if it improves.', adv_neutral='AI watch: {pair} is near its usual level ({p}th percentile of 90 days) — no strong signal either way.', progress='Level {level} of {max} · {streak} check-in day(s) in your current streak · {active} active challenge(s) · {badges} badge(s) earned.', afford_yes='Yes — after spending {amount}, your lowest projected balance stays at {lowest} ({date}).', afford_careful="Possible but tight: your lowest projected balance would be {lowest} ({date}), below your buffer or this month's budget.{wait}", afford_no='Not right now: you would run short around {date} (lowest {lowest}).{wait}', wait=' Safer from {date}.', scholarships='You are tracking {n} application(s). Next deadline: {name} on {date}.', scholarships_none='No scholarships tracked yet — add one on the Student money page, or tell me its name and deadline.', cashflow='Lowest projected balance: {amount} on {date}.', cashflow_short='Shortfall expected: your balance drops below zero around {date} (lowest {amount}).', offline="Offline rule planner — not an AI model. Configure a model for open-ended conversation.",
               missing="I need a few more details before preparing anything: {fields}.",
               prepared="Draft prepared from a sandbox quote. Review it and authorize it yourself — I cannot approve payments.",
               executed="Submitted. Current status: {status}. Submitted is not the same as completed; I will keep tracking it.",
               need_approval="This payment needs your explicit approval in the payment screen first.",
               nothing="I could not find a payment to act on. Open the payment and try again.",
               info="Here is what I found. Each card is labeled as reference data, simulation, ledger record or estimate.",
               form="Fill in the recipient in the panel beside the chat; I will continue as soon as it is saved.", logged="Logged as pending. Confirm it on the Spending page.", remembered="Noted. I will remember this; you can review or delete it on the Memory page.", recalled="From memory: {n} note(s) and {m} earlier conversation(s) match.", recalled_none="I have nothing remembered about that.", forgot="Forgotten.", forgot_none="I found no remembered note matching that.", sensitive="I never store passwords, keys or full account numbers in memory.",
               help="I can check balances and rates, compare options, prepare and track payments, and plan goals. "
                    "Try: “Send 100 AUD to family for living costs”.",
               fields=dict(amount="amount", recipient="recipient", purpose="purpose", pair="currency pair", percent="percentage")),
    "zh-CN": dict(adv_good_time='AI 盯盘：{pair} 现在是换汇的好时机——{rate}，优于近 90 天 {p}% 的时候。', adv_wait='AI 盯盘：{pair} 处于近 90 天偏低位置（只优于 {p}% 的时候）；如果不急，可以再等等。', adv_deadline='AI 盯盘：你的截止日期快到了——建议尽快换 {pair}，不要再等（现在 {rate}）。', adv_below_floor='AI 盯盘：{pair} 现在是 {rate}，低于你能接受的汇率；回升时我会提醒你。', adv_neutral='AI 盯盘：{pair} 处于平常水平（近 90 天第 {p} 百分位）——暂无明显信号。', progress='等级 {level}/{max} · 当前连续 {streak} 天打理财务 · {active} 个进行中的挑战 · 已获得 {badges} 枚徽章。', afford_yes='可以——花掉 {amount} 后，预计最低余额仍有 {lowest}（{date}）。', afford_careful='可以但偏紧：预计最低余额会是 {lowest}（{date}），低于你的安全垫或本月预算。{wait}', afford_no='现在不建议：大约 {date} 会出现缺口（最低 {lowest}）。{wait}', wait='从 {date} 起会更稳妥。', scholarships='你正在跟踪 {n} 个申请。最近的截止：{name}，{date}。', scholarships_none='还没有跟踪任何奖学金——可在“学生理财”页添加，或告诉我名称和截止日期。', cashflow='预计最低余额：{date} 时 {amount}。', cashflow_short='预计会出现缺口：大约 {date} 余额跌破零（最低 {amount}）。', offline="离线规则规划器 —— 不是 AI 大模型。配置模型后可进行开放式对话。",
                  missing="在准备任何操作前，我还需要：{fields}。",
                  prepared="已根据沙盒报价创建草稿。请你亲自核对并授权——我无法批准支付。",
                  executed="已提交。当前状态：{status}。已提交不等于已完成，我会继续跟踪。",
                  need_approval="这笔支付需要你先在支付详情中明确授权。",
                  nothing="没有找到可操作的支付。请打开支付详情后再试。",
                  info="以下是查询结果。每张卡片都标明了是参考数据、模拟、账本记录还是估算。",
                  form="请在聊天右侧的面板里填写收款人信息，保存后我会立刻继续。", logged="已记为待确认，请在“记账”页确认。", remembered="已记住。你可以在“记忆”页查看或删除。", recalled="记忆中有 {n} 条笔记和 {m} 段过往对话与此相关。", recalled_none="关于这个我没有任何记忆。", forgot="已忘记。", forgot_none="没有找到匹配的记忆笔记。", sensitive="我绝不会把密码、密钥或完整账号存进记忆。",
                  help="我可以查询余额和汇率、比较方案、准备并跟踪支付、规划目标。试试：“给 family 汇 100 澳元用于生活费”。",
                  fields=dict(amount="金额", recipient="收款人", purpose="用途", pair="币种", percent="百分比")),
    "zh-TW": dict(adv_good_time='AI 盯盤：{pair} 現在是換匯的好時機——{rate}，優於近 90 天 {p}% 的時候。', adv_wait='AI 盯盤：{pair} 處於近 90 天偏低位置（只優於 {p}% 的時候）；如果不急，可以再等等。', adv_deadline='AI 盯盤：你的截止日期快到了——建議盡快換 {pair}，不要再等（現在 {rate}）。', adv_below_floor='AI 盯盤：{pair} 現在是 {rate}，低於你能接受的匯率；回升時我會提醒你。', adv_neutral='AI 盯盤：{pair} 處於平常水準（近 90 天第 {p} 百分位）——暫無明顯訊號。', progress='等級 {level}/{max} · 目前連續 {streak} 天打理財務 · {active} 個進行中的挑戰 · 已獲得 {badges} 枚徽章。', afford_yes='可以——花掉 {amount} 後，預計最低餘額仍有 {lowest}（{date}）。', afford_careful='可以但偏緊：預計最低餘額會是 {lowest}（{date}），低於你的安全墊或本月預算。{wait}', afford_no='現在不建議：大約 {date} 會出現缺口（最低 {lowest}）。{wait}', wait='從 {date} 起會更穩妥。', scholarships='你正在追蹤 {n} 個申請。最近的截止：{name}，{date}。', scholarships_none='還沒有追蹤任何獎學金——可在「學生理財」頁新增，或告訴我名稱和截止日期。', cashflow='預計最低餘額：{date} 時 {amount}。', cashflow_short='預計會出現缺口：大約 {date} 餘額跌破零（最低 {amount}）。', offline="離線規則規劃器 —— 不是 AI 大模型。設定模型後可進行開放式對話。",
                  missing="在準備任何操作前，我還需要：{fields}。",
                  prepared="已根據沙盒報價建立草稿。請你親自核對並授權——我無法批准付款。",
                  executed="已提交。目前狀態：{status}。已提交不等於已完成，我會持續追蹤。",
                  need_approval="這筆付款需要你先在付款詳情中明確授權。",
                  nothing="沒有找到可操作的付款。請開啟付款詳情後再試。",
                  info="以下是查詢結果。每張卡片都標明了是參考資料、模擬、帳本紀錄還是估算。",
                  form="請在聊天右側的面板裡填寫收款人資料，儲存後我會立刻繼續。", logged="已記為待確認，請在「記帳」頁確認。", remembered="已記住。你可以在「記憶」頁查看或刪除。", recalled="記憶中有 {n} 則筆記和 {m} 段過往對話與此相關。", recalled_none="關於這個我沒有任何記憶。", forgot="已忘記。", forgot_none="沒有找到符合的記憶筆記。", sensitive="我絕不會把密碼、金鑰或完整帳號存進記憶。",
                  help="我可以查詢餘額和匯率、比較方案、準備並追蹤付款、規劃目標。試試：「給 family 匯 100 澳幣用於生活費」。",
                  fields=dict(amount="金額", recipient="收款人", purpose="用途", pair="幣別", percent="百分比")),
    "vi": dict(adv_good_time='AI theo dõi: {pair} đang là lúc tốt để đổi — {rate}, tốt hơn {p}% số ngày trong 90 ngày qua.', adv_wait='AI theo dõi: {pair} đang thấp so với 90 ngày qua (chỉ tốt hơn {p}%); nếu chưa gấp, có thể chờ thêm.', adv_deadline='AI theo dõi: sắp đến hạn — nên đổi {pair} sớm thay vì chờ (hiện {rate}).', adv_below_floor='AI theo dõi: {pair} đang là {rate}, thấp hơn mức bạn chấp nhận; tôi sẽ nhắc khi tỷ giá tốt lên.', adv_neutral='AI theo dõi: {pair} ở mức bình thường (bách phân vị {p} trong 90 ngày) — chưa có tín hiệu rõ.', progress='Cấp {level}/{max} · chuỗi hiện tại {streak} ngày chăm sóc tài chính · {active} thử thách đang chạy · {badges} huy hiệu đã nhận.', afford_yes='Được — sau khi chi {amount}, số dư dự kiến thấp nhất vẫn là {lowest} ({date}).', afford_careful='Được nhưng hơi sát: số dư thấp nhất sẽ là {lowest} ({date}), dưới mức dự phòng hoặc ngân sách tháng này.{wait}', afford_no='Chưa nên lúc này: bạn sẽ thiếu tiền vào khoảng {date} (thấp nhất {lowest}).{wait}', wait=' An toàn hơn từ {date}.', scholarships='Bạn đang theo dõi {n} hồ sơ. Hạn gần nhất: {name} ngày {date}.', scholarships_none='Chưa theo dõi học bổng nào — thêm ở trang Tài chính sinh viên, hoặc cho tôi biết tên và hạn nộp.', cashflow='Số dư dự kiến thấp nhất: {amount} vào {date}.', cashflow_short='Dự kiến thiếu hụt: số dư xuống dưới 0 vào khoảng {date} (thấp nhất {amount}).', offline="Bộ lập kế hoạch theo quy tắc ngoại tuyến — không phải mô hình AI. Hãy cấu hình mô hình để trò chuyện tự do.",
               missing="Tôi cần thêm vài thông tin trước khi chuẩn bị: {fields}.",
               prepared="Đã tạo bản nháp từ báo giá sandbox. Hãy tự kiểm tra và ủy quyền — tôi không thể phê duyệt thanh toán.",
               executed="Đã gửi. Trạng thái hiện tại: {status}. Đã gửi không có nghĩa là đã hoàn tất; tôi sẽ tiếp tục theo dõi.",
               need_approval="Khoản thanh toán này cần bạn phê duyệt rõ ràng trước trong màn hình thanh toán.",
               nothing="Không tìm thấy khoản thanh toán để thực hiện. Hãy mở chi tiết thanh toán rồi thử lại.",
               info="Đây là kết quả. Mỗi thẻ ghi rõ là dữ liệu tham chiếu, mô phỏng, sổ cái hay ước tính.",
               form="Hãy điền thông tin người nhận ở bảng bên cạnh khung chat; tôi sẽ tiếp tục ngay khi lưu xong.", logged="Đã ghi là chờ xác nhận. Hãy xác nhận ở trang Chi tiêu.", remembered="Đã ghi nhớ. Bạn có thể xem hoặc xóa trong trang Bộ nhớ.", recalled="Trong bộ nhớ có {n} ghi chú và {m} cuộc trò chuyện trước liên quan.", recalled_none="Tôi không nhớ gì về điều đó.", forgot="Đã quên.", forgot_none="Không tìm thấy ghi chú nào khớp.", sensitive="Tôi không bao giờ lưu mật khẩu, khóa hay số tài khoản đầy đủ vào bộ nhớ.",
               help="Tôi có thể xem số dư và tỷ giá, so sánh phương án, chuẩn bị và theo dõi thanh toán. "
                    "Thử: “Gửi 100 AUD cho family để chi tiêu sinh hoạt”.",
               fields=dict(amount="số tiền", recipient="người nhận", purpose="mục đích", pair="cặp tiền tệ", percent="phần trăm")),
    "ja": dict(adv_good_time='AI ウォッチ：{pair} は今が両替のよいタイミングです——{rate}、直近 90 日の {p}% より有利。', adv_wait='AI ウォッチ：{pair} は直近 90 日で低め（{p}% より有利なだけ）。急がなければ待つのも妥当です。', adv_deadline='AI ウォッチ：期限が近いので、待たずに早めに {pair} を両替しましょう（現在 {rate}）。', adv_below_floor='AI ウォッチ：{pair} は {rate} で、許容できるレートを下回っています。改善したらお知らせします。', adv_neutral='AI ウォッチ：{pair} はいつもの水準（90 日の {p} パーセンタイル）——はっきりしたシグナルはありません。', progress='レベル {level}/{max} · 現在の連続記録 {streak} 日 · 進行中のチャレンジ {active} 件 · 獲得バッジ {badges} 個。', afford_yes='大丈夫です——{amount} 使っても、予測残高の最低値は {lowest}（{date}）です。', afford_careful='可能ですがぎりぎりです：予測残高の最低値は {lowest}（{date}）で、安全資金か今月の予算を下回ります。{wait}', afford_no='今はおすすめしません：{date} ごろに不足します（最低 {lowest}）。{wait}', wait='{date} 以降なら安全です。', scholarships='{n} 件の応募を管理しています。次の締切：{name}（{date}）。', scholarships_none='まだ奨学金は登録されていません。「学生のお金」ページで追加するか、名前と締切を教えてください。', cashflow='予測残高の最低値：{date} に {amount}。', cashflow_short='不足が見込まれます：{date} ごろ残高がマイナスになります（最低 {amount}）。', offline="オフラインのルールプランナーです（AI モデルではありません）。自由な会話にはモデルを設定してください。",
               missing="準備の前に、次の情報が必要です：{fields}。",
               prepared="サンドボックス見積もりから下書きを作成しました。ご自身で確認して承認してください。私は支払いを承認できません。",
               executed="送信しました。現在の状態：{status}。送信済みは完了ではありません。引き続き追跡します。",
               need_approval="この支払いには、まず支払い画面での明示的な承認が必要です。",
               nothing="操作できる支払いが見つかりません。支払い詳細を開いてから再試行してください。",
               info="結果です。各カードには参考データ・シミュレーション・台帳記録・推定の区別が表示されます。",
               form="チャット横のパネルで受取人を入力してください。保存されたらすぐに続けます。", logged="保留中として記録しました。「家計簿」ページで確定してください。", remembered="覚えました。「メモリー」ページで確認・削除できます。", recalled="メモリーに一致するメモが {n} 件、過去の会話が {m} 件あります。", recalled_none="それについて覚えていることはありません。", forgot="忘れました。", forgot_none="一致するメモは見つかりませんでした。", sensitive="パスワード、鍵、完全な口座番号をメモリーに保存することはありません。",
               help="残高や為替の確認、比較、支払いの準備と追跡、目標の計画ができます。例：「family に生活費として 100 AUD 送金」。",
               fields=dict(amount="金額", recipient="受取人", purpose="目的", pair="通貨ペア", percent="割合")),
    "ko": dict(adv_good_time='AI 감시: {pair} 지금이 환전하기 좋은 때예요 — {rate}, 최근 90일 중 {p}%보다 유리해요.', adv_wait='AI 감시: {pair}가 최근 90일 기준 낮은 편이에요({p}%보다만 유리). 급하지 않다면 기다려도 좋아요.', adv_deadline='AI 감시: 마감이 가까워요 — 기다리지 말고 {pair}를 곧 환전하세요(현재 {rate}).', adv_below_floor='AI 감시: {pair}가 {rate}로 받아들일 수 있는 환율보다 낮아요. 나아지면 알려 드릴게요.', adv_neutral='AI 감시: {pair}가 평소 수준이에요(90일 기준 {p} 백분위) — 뚜렷한 신호는 없어요.', progress='레벨 {level}/{max} · 현재 연속 {streak}일 · 진행 중인 챌린지 {active}개 · 획득한 배지 {badges}개.', afford_yes='괜찮아요 — {amount}를 써도 예상 최저 잔액은 {lowest}({date})입니다.', afford_careful='가능하지만 빠듯해요: 예상 최저 잔액이 {lowest}({date})로 비상금이나 이번 달 예산보다 낮아요.{wait}', afford_no='지금은 어려워요: {date}쯤 잔액이 부족해집니다(최저 {lowest}).{wait}', wait=' {date}부터는 더 안전해요.', scholarships='지원서 {n}개를 관리 중입니다. 가장 가까운 마감: {name}, {date}.', scholarships_none='아직 관리 중인 장학금이 없습니다. ‘학생 재정’ 페이지에서 추가하거나 이름과 마감일을 알려 주세요.', cashflow='예상 최저 잔액: {date}에 {amount}.', cashflow_short='부족이 예상됩니다: {date}쯤 잔액이 0 아래로 떨어집니다(최저 {amount}).', offline="오프라인 규칙 플래너입니다(AI 모델이 아님). 자유로운 대화를 하려면 모델을 설정하세요.",
               missing="준비하기 전에 다음 정보가 필요합니다: {fields}.",
               prepared="샌드박스 견적으로 초안을 만들었습니다. 직접 확인하고 승인해 주세요. 저는 결제를 승인할 수 없습니다.",
               executed="제출했습니다. 현재 상태: {status}. 제출은 완료와 다릅니다. 계속 추적하겠습니다.",
               need_approval="이 결제는 먼저 결제 화면에서 명시적으로 승인해야 합니다.",
               nothing="처리할 결제를 찾지 못했습니다. 결제 상세를 연 뒤 다시 시도하세요.",
               info="조회 결과입니다. 각 카드에 참고 데이터, 시뮬레이션, 원장 기록, 추정이 표시됩니다.",
               form="채팅 옆 패널에 수취인 정보를 입력해 주세요. 저장되면 바로 이어서 진행할게요.", logged="대기 중으로 기록했어요. 지출 페이지에서 확인해 주세요.", remembered="기억했습니다. 기억 페이지에서 확인하거나 삭제할 수 있습니다.", recalled="기억 속에 관련 메모 {n}개와 이전 대화 {m}개가 있습니다.", recalled_none="그것에 대해 기억하는 것이 없습니다.", forgot="잊었습니다.", forgot_none="일치하는 기억 메모를 찾지 못했습니다.", sensitive="비밀번호, 키, 전체 계좌번호는 절대 기억에 저장하지 않습니다.",
               help="잔액·환율 조회, 옵션 비교, 결제 준비와 추적, 목표 계획을 도와드립니다. 예: “family에게 생활비로 100 AUD 송금”.",
               fields=dict(amount="금액", recipient="수취인", purpose="용도", pair="통화쌍", percent="비율")),
}


def has(text, intent):
    if intent == "prepare" and re.search(r"[汇匯转轉寄](?![率换換])", text):
        return True
    return any(word in text for word in KEYWORDS[intent])


class RulePlanner:
    def __init__(self, agent):
        self.agent = agent

    @staticmethod
    def currencies(text):
        spans = []
        for match in re.finditer(r"(?<![A-Za-z])([A-Za-z]{3})(?![A-Za-z])", text):
            code = match.group(1).upper()
            if code in CURRENCY_WORDS:
                spans.append((match.start(), match.end(), code))
        for code, words in CURRENCY_WORDS.items():
            for w in words[1:]:
                for m in re.finditer(re.escape(w), text):
                    spans.append((m.start(), m.end(), code))
        # A word inside a longer currency word (ドル in 豪ドル) belongs to the longer one.
        kept = [s for s in spans if not any(o[0] <= s[0] and s[1] <= o[1] and o[1] - o[0] > s[1] - s[0] for o in spans)]
        ordered = []
        for _, _, code in sorted(kept):
            if code not in ordered:
                ordered.append(code)
        return ordered

    @staticmethod
    def amount(message):
        clean = re.sub(r"0x[0-9a-fA-F]{6,}|\b[0-9a-f]{8}(?:-[0-9a-f-]{27})?\b|\d{4}-\d{2}-\d{2}", " ", message.lower())
        clean = clean.replace(",", "")
        words = sorted({w for ws in CURRENCY_WORDS.values() for w in ws}, key=len, reverse=True)
        m = re.search(r"(?<![0-9.])(\d{1,12}(?:\.\d{1,18})?)\s*(?:" + "|".join(map(re.escape, words)) + ")", clean)
        if not m:
            m = re.search(r"(?<![0-9.])(\d{1,12}(?:\.\d{1,18})?)(?![0-9.%])", clean)
        return m.group(1) if m else None

    def understand(self, message, session):
        text = message.lower()
        recipients = self.agent.finance.recipients()
        entities = {}
        amount = self.amount(message)
        if amount:
            entities["amount"] = amount
        codes = self.currencies(text)
        if codes:
            entities["source"] = codes[0]
        if len(codes) > 1:
            entities["target"] = codes[1]
        for r in recipients:
            if r["id"].lower() in text or r["name"].lower() in text:
                entities["recipient"] = r["id"]
                if r["rail"] == "evm":
                    entities.setdefault("source", "ETH")
                    entities.setdefault("target", "ETH")
                elif r.get("currency") and "target" not in entities and entities.get("source") != r["currency"]:
                    entities["target"] = r["currency"]
                break
        if any(w in text for w in RECEIVE):
            entities["receive"] = True  # the amount is what the recipient gets
        if "recipient" not in entities:
            for pattern in NEW_NAME:
                m = re.search(pattern, message)
                if m and m.group(1).lower() not in ("me", "my", "family's"):
                    entities["new_name"] = m.group(1).strip()
                    break
        for pattern in PURPOSE:
            m = re.search(pattern, message, re.I)
            if m:
                entities["purpose"] = m.group(1).strip(" .。!！")
                break
        percent = re.search(r"([-+]?\d+(?:\.\d+)?)\s*%", message)
        if percent:
            value = Decimal(percent.group(1))
            if value > 0 and any(w in text for w in DOWN):
                value = -value
            entities["percent"] = str(value)
        tid = re.search(r"\b([0-9a-f]{8})(?:-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})?\b", text)
        if tid:
            entities["transfer"] = tid.group(0)
        intent = next((i for i in ("forget", "recall", "remember", "timing", "progress", "afford", "scholarship", "cashflow", "insights", "execute", "track", "forecast", "scenario", "compare", "prepare", "rates",
                                   "balance", "reminders", "goals", "credit", "expense") if has(text, i)), None)
        if intent in ("forget", "recall", "remember"):
            entities = {"note": self.after_keyword(message, intent)}
            return intent, entities
        if intent == "scenario" and "percent" not in entities:
            intent = "rates"
        if intent is None and "percent" in entities and "amount" in entities:
            intent = "scenario"
        # Follow-up: fill in what the previous turn asked for.
        state = self.load(session)
        if state and state.get("missing") and intent in (None, state["intent"]):
            merged = dict(state["entities"])
            for key, value in entities.items():
                merged.setdefault(key, value)
            if "purpose" in state["missing"] and "purpose" not in entities and intent is None:
                merged["purpose"] = message.strip()[:80]
            entities, intent = merged, state["intent"]
        return intent or "help", entities

    @staticmethod
    def after_keyword(message, intent):
        low = message.lower()
        for word in sorted(KEYWORDS[intent], key=len, reverse=True):
            i = low.find(word)
            if i >= 0:
                rest = message[i + len(word):].strip(" ,.:;!?，。：；！？")
                rest = re.sub(r"^(?:that|about|rằng|là|一下|：)\s*", "", rest, flags=re.I).strip()
                return rest or message.strip()
        return message.strip()

    def load(self, session):
        with self.agent.finance.store.read() as c:
            row = c.execute("SELECT body FROM messages WHERE session=? AND role='planner_state' ORDER BY id DESC LIMIT 1",
                            (session,)).fetchone()
        try:
            return json.loads(row[0]) if row else None
        except ValueError:
            return None

    def save_state(self, session, intent, entities, missing):
        with self.agent.finance.store.tx() as c:
            c.execute("INSERT INTO messages(session,role,body) VALUES (?,?,?)",
                      (session, "planner_state", canonical(dict(intent=intent, entities=entities, missing=missing))))

    def stream(self, message, session, language, rid):
        t = TEXT[language]
        yield {"type": "start", "mode": "rules", "request_id": rid, "note": t["offline"]}
        intent, e = self.understand(message, session)
        steps, missing = [], []
        src, dst = e.get("source"), e.get("target")
        pair = dict(source=src, target=dst) if src and dst else None
        if intent == "balance":
            steps = [("get_balances", {})]
        elif intent == "afford":
            if e.get("amount"):
                steps = [("afford_check", dict(amount=e["amount"], currency=src or "", date="", label=message[:80]))]
            else:
                missing = ["amount"]
        elif intent == "timing":
            if not pair:
                watched = [w for w in self.agent.finance.watches() if w["active"]]
                if watched:
                    pair = dict(source=watched[0]["source"], target=watched[0]["target"])
            if pair:
                steps = [("exchange_advice", pair)]
            else:
                missing = ["pair"]
        elif intent == "progress":
            steps = [("progress_overview", {})]
        elif intent == "scholarship":
            steps = [("list_scholarships", {})]
        elif intent == "cashflow":
            steps = [("cashflow_plan", dict(currency=src or ""))]
        elif intent == "insights":
            steps = [("spending_insights", dict(period="week" if any(w in message.lower() for w in WEEK) else "month"))]
        elif intent == "expense":
            steps = [("log_expense", {"text": self.after_keyword(message, "expense")})]
        elif intent == "rates":
            if pair:
                steps = [("latest_rate", pair), ("rate_history", dict(pair, days="30"))]
            else:
                missing = ["pair"]
        elif intent == "forecast":
            steps = [("forecast_rate", pair)] if pair else []
            missing = [] if pair else ["pair"]
        elif intent == "compare":
            if not pair:
                missing.append("pair")
            if not e.get("amount"):
                missing.append("amount")
            if not missing:
                steps = [("latest_rate", pair), ("compare_options", dict(pair, amount=e["amount"], rank="receive"))]
        elif intent == "scenario":
            missing = [k for k, ok in (("pair", pair), ("amount", e.get("amount")), ("percent", e.get("percent"))) if not ok]
            if not missing:
                steps = [("scenario", dict(pair, amount=e["amount"], rate_change_pct=e["percent"]))]
        elif intent == "prepare":
            if not e.get("amount"):
                missing.append("amount")
            if not e.get("recipient"):
                missing.append("recipient")
            if not src or not dst:
                missing.append("pair")
            if not e.get("purpose"):
                missing.append("purpose")
            if not missing:
                money = dict(receive_amount=e["amount"]) if e.get("receive") else dict(amount=e["amount"])
                steps = [("get_balances", {}), ("prepare_payment", dict(money, source=src, target=dst,
                                                                       recipient_id=e["recipient"], purpose=e["purpose"]))]
            elif "recipient" in missing:
                steps = [("request_recipient_details", dict(name=e.get("new_name", ""), currency=dst or "", country="", reason="recipient not registered"))]
        elif intent in ("execute", "track"):
            target = self.find_transfer(e.get("transfer"), intent)
            if target:
                steps = [("get_payment", dict(transfer_id=target["id"]))]
                if intent == "execute":
                    steps.append(("execute_payment", dict(transfer_id=target["id"])))
                else:
                    steps.append(("reconcile_payment", dict(transfer_id=target["id"])))
        elif intent == "reminders":
            steps = [("reminders", {})]
        elif intent == "goals":
            steps = [("goals_overview", {})]
        elif intent == "credit":
            steps = [("habits_overview", {})]
        elif intent == "remember":
            note = e["note"]
            kind = "routine" if any(w in note.lower() for w in ROUTINE) else "preference" if any(w in note.lower() for w in PREFER) else "fact"
            steps = [("remember_note", {"text": note, "kind": kind})]
        elif intent == "recall":
            steps = [("recall_memory", {"query": e["note"]})]
        elif intent == "forget":
            match = self.agent.memory.recall(e["note"], limit=1)["notes"]
            steps = [("forget_note", {"note_id": match[0]["id"]})] if match else []
        yield {"type": "understand", "intent": intent, "summary": message[:160], "entities": e,
               "missing": [t["fields"].get(m, m) for m in missing]}
        yield {"type": "plan", "steps": [{"tool": name, "why": ""} for name, _ in steps]}
        self.save_state(session, intent, e, missing)
        results = []
        for name, args in steps:
            yield {"type": "tool", "tool": name}
            event = self.agent.run_tool(name, args, session, rid)
            results.append(event)
            yield event
            if not event["ok"]:
                break
        text = self.reply(t, intent, missing, results)
        self.agent.save(session, message, text)
        yield {"type": "message", "text": text}
        yield {"type": "done", "mode": "rules"}

    def find_transfer(self, prefix, intent):
        wanted = ("approved", "draft") if intent == "execute" else ("pending", "unknown", "approved", "draft")
        for t in self.agent.finance.history(limit=50):
            if prefix and t["id"].startswith(prefix[:8]):
                return t
            if not prefix and t["status"] in wanted:
                return t
        return None

    @staticmethod
    def reply(t, intent, missing, results):
        if results and results[-1]["ok"] and results[-1]["tool"] == "request_recipient_details":
            return t["form"]  # the form beside the chat collects what is missing
        if missing:
            return t["missing"].format(fields=", ".join(t["fields"].get(m, m) for m in missing))
        if not results:
            return t["nothing"] if intent in ("execute", "track") else t["forgot_none"] if intent == "forget" else t["help"]
        last = results[-1]
        if not last["ok"]:
            if last.get("code") == "approval_required":
                return t["need_approval"]
            if last.get("code") == "memory_sensitive":
                return t["sensitive"]
            return last["error"]
        if last["tool"] == "request_recipient_details":
            return t["form"]
        if last["tool"] == "log_expense":
            return t["logged"]
        if last["tool"] == "exchange_advice":
            r = last["result"]
            text = t["adv_" + r["verdict"]].format(pair=f'{r["source"]}→{r["target"]}', rate=r["signals"]["rate"],
                                                   p=round(r["signals"]["percentile_90d"]))
            return text + (" " + r["explanation"] if r.get("explanation") else "")
        if last["tool"] == "progress_overview":
            r = last["result"]
            return t["progress"].format(level=r["level"], max=r["max_level"], streak=r["streak"]["current"], active=len(r["active"]),
                                        badges=sum(1 for b in r["badges"] if b["earned"]))
        if last["tool"] == "afford_check":
            r = last["result"]
            wait = t["wait"].format(date=r["wait_until"]) if r.get("wait_until") else ""
            neg = next((x["date"] for x in r["reasons"] if x["code"] == "negative"), r["lowest_date"])
            return t["afford_" + r["verdict"]].format(amount=money(r["amount"], r["currency"]), lowest=money(r["lowest_after"], r["currency"]),
                                                      date=neg if r["verdict"] == "no" else r["lowest_date"], wait=wait)
        if last["tool"] == "spending_insights":
            return "\n".join("· " + x["text"] for x in last["result"]["tips"][:4])
        if last["tool"] == "list_scholarships":
            rows = [x for x in last["result"] if x["open"] and x["deadline"]]
            if not last["result"]:
                return t["scholarships_none"]
            nxt = rows[0] if rows else last["result"][0]
            return t["scholarships"].format(n=len(last["result"]), name=nxt["name"], date=nxt.get("deadline") or "—")
        if last["tool"] == "cashflow_plan":
            r = last["result"]
            key = "cashflow_short" if r["first_negative"] else "cashflow"
            return t[key].format(amount=money(r["lowest"]["amount"], r["currency"]), date=r["first_negative"] or r["lowest"]["date"])
        if last["tool"] == "remember_note":
            return t["remembered"]
        if last["tool"] == "forget_note":
            return t["forgot"]
        if last["tool"] == "recall_memory":
            r = last["result"]
            return t["recalled"].format(n=len(r["notes"]), m=len(r["episodes"])) if r["notes"] or r["episodes"] else t["recalled_none"]
        if last["tool"] == "prepare_payment":
            return t["prepared"]
        if last["tool"] in ("execute_payment", "reconcile_payment"):
            r = last["result"]
            return t["executed"].format(status=r["status"])
        return t["info"]
