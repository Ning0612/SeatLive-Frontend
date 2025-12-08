"""
SeatLive Streamlit 前端應用程式

顯示餐廳座位即時狀態和本週人流統計
資料來源：Firebase Realtime Database
"""
import os
import sys
import streamlit as st
import pandas as pd
import firebase_admin
from firebase_admin import credentials, db
from datetime import datetime
import plotly.express as px
import plotly.graph_objects as go
from dotenv import load_dotenv

# 載入環境變數
load_dotenv()

# 頁面設定
st.set_page_config(
    page_title="SeatLive - 餐廳座位監控",
    page_icon="🪑",
    layout="wide",
    initial_sidebar_state="expanded"
)

# CSS 樣式
st.markdown("""
<style>
    .main-header {
        font-size: 2.5rem;
        font-weight: bold;
        color: #1f77b4;
        text-align: center;
        margin-bottom: 2rem;
    }
    .metric-card {
        background-color: #f0f2f6;
        padding: 1rem;
        border-radius: 0.5rem;
        text-align: center;
    }
    .seat-occupied {
        background-color: #ff6b6b;
        color: white;
        padding: 0.5rem;
        border-radius: 0.3rem;
        font-weight: bold;
    }
    .seat-available {
        background-color: #51cf66;
        color: white;
        padding: 0.5rem;
        border-radius: 0.3rem;
        font-weight: bold;
    }
</style>
""", unsafe_allow_html=True)


@st.cache_resource
def initialize_firebase():
    """初始化 Firebase 連接（支援本地開發和 Streamlit Cloud）"""
    try:
        # 檢查是否已經初始化
        if not firebase_admin._apps:
            # 優先使用 Streamlit secrets（用於 Streamlit Cloud 部署）
            if 'firebase' in st.secrets:
                # Cloud 模式：從 Secrets 讀取 firebase 段落
                firebase_section = st.secrets['firebase']
                firebase_config = dict(firebase_section)

                required_keys = {
                    'type', 'project_id', 'private_key_id', 'private_key',
                    'client_email', 'client_id', 'token_uri'
                }

                # 嘗試多種常見位置取得 DB URL（頂層為主，兼容少數放在段落內的狀況）
                database_url = (
                    st.secrets.get('FIREBASE_DATABASE_URL')
                    or firebase_config.get('FIREBASE_DATABASE_URL')
                    or firebase_config.get('databaseURL')
                    or firebase_config.get('database_url')
                )

                missing_keys = required_keys - set(firebase_config.keys())
                if missing_keys or not database_url:
                    # 只顯示缺少的欄位名稱，不顯示敏感值
                    missing_text = ", ".join(sorted(missing_keys)) if missing_keys else "(無缺漏)"
                    present_text = ", ".join(sorted(firebase_config.keys())) or "(無)"
                    db_present = bool(database_url)
                    st.error(
                        "❌ Streamlit Secrets 缺少必要欄位，請確認在 App Settings > Secrets 以 TOML 形式設定 [firebase] 與 FIREBASE_DATABASE_URL。"
                    )
                    st.info(
                        f"缺少欄位: {missing_text}\n"
                        f"已提供欄位: {present_text}\n"
                        f"FIREBASE_DATABASE_URL 已提供: {db_present}"
                    )
                    st.caption(
                        "範例格式:\n"
                        "[firebase]\n"
                        "type='service_account'\n"
                        "project_id='your-project-id'\n"
                        "private_key_id='...'\n"
                        "private_key='-----BEGIN PRIVATE KEY-----\\n...\\n-----END PRIVATE KEY-----\\n'\n"
                        "client_email='...@...iam.gserviceaccount.com'\n"
                        "client_id='...'\n"
                        "token_uri='https://oauth2.googleapis.com/token'\n"
                        "FIREBASE_DATABASE_URL='https://<project>.firebaseio.com/'"
                    )
                    return False

                # 確保換行符號正確解析
                if isinstance(firebase_config.get('private_key'), str):
                    firebase_config['private_key'] = firebase_config['private_key'].replace('\\n', '\n')

                cred = credentials.Certificate(firebase_config)
                st.success("✅ 使用 Streamlit Secrets 初始化 Firebase")
            else:
                # 本地開發模式：使用環境變數
                credentials_path = os.getenv('FIREBASE_CREDENTIALS_PATH')
                database_url = os.getenv('FIREBASE_DATABASE_URL')

                if not credentials_path or not database_url:
                    st.error("❌ 未設定 Firebase 憑證，請檢查 .env 檔案或 Streamlit Secrets")
                    return False

                # 取得憑證檔案完整路徑（專案根目錄）
                if not os.path.isabs(credentials_path):
                    # frontend/streamlit_app.py -> frontend/ -> project_root/
                    base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
                    credentials_path = os.path.join(base_dir, credentials_path)

                if not os.path.exists(credentials_path):
                    st.error(f"❌ 找不到 Firebase 憑證檔案: {credentials_path}")
                    return False

                cred = credentials.Certificate(credentials_path)
                st.success("✅ 使用本地憑證初始化 Firebase")

            # 初始化 Firebase
            firebase_admin.initialize_app(cred, {
                'databaseURL': database_url
            })

        return True
    except Exception:
        # 避免將詳細路徑與環境洩漏給終端使用者
        st.error("❌ Firebase 初始化失敗，請稍後再試或聯絡管理員。")
        return False


def get_seat_status():
    """從 Firebase 讀取即時座位狀態"""
    try:
        ref = db.reference('/seat_status')
        data = ref.get()

        if not data:
            return None

        # 轉換為 DataFrame
        seats_list = []
        for seat_id, info in data.items():
            seats_list.append({
                'seat_id': seat_id,
                'status': info.get('status', 'unknown'),
                'status_zh': info.get('status_zh', '未知'),
                'last_update': info.get('last_update', '')
            })

        df = pd.DataFrame(seats_list)
        df = df.sort_values('seat_id')
        return df

    except Exception as e:
        st.error(f"❌ 讀取座位狀態失敗: {e}")
        return None


def get_weekly_occupancy(week_number=None):
    """從 Firebase 讀取每週統計資料"""
    try:
        if week_number is None:
            week_number = datetime.now().isocalendar()[1]

        ref = db.reference(f'/occupancy_statistics/week_{week_number}')
        data = ref.get()

        if not data:
            return None, week_number

        # 轉換為 DataFrame
        df = pd.DataFrame(data.get('data', []))
        return df, week_number

    except Exception as e:
        st.error(f"❌ 讀取每週統計失敗: {e}")
        return None, week_number


def display_seat_status_page():
    """顯示即時座位狀態和本週人流統計頁面"""
    st.markdown('<div class="main-header">🪑 SeatLive 餐廳座位監控</div>', unsafe_allow_html=True)

    # 讀取座位狀態
    df = get_seat_status()

    if df is None or df.empty:
        st.warning("⚠️ 目前沒有座位狀態資料")
        return

    # 統計資訊
    total_seats = len(df)
    occupied_seats = len(df[df['status'] == 'occupied'])
    available_seats = total_seats - occupied_seats
    occupancy_rate = (occupied_seats / total_seats * 100) if total_seats > 0 else 0

    # 顯示現在時間
    current_time = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    st.caption(f"🕒 現在時間：{current_time}")

    # ============================================================
    # 即時座位狀態區塊
    # ============================================================
    st.subheader("📊 即時座位狀態")

    # 顯示統計卡片
    col1, col2, col3, col4 = st.columns(4)

    with col1:
        st.metric("總座位數", f"{total_seats} 個")

    with col2:
        st.metric("已佔用", f"{occupied_seats} 個")

    with col3:
        st.metric("空位", f"{available_seats} 個")

    with col4:
        # 根據佔用率設定顏色
        if occupancy_rate <= 30:
            color = "#51cf66"  # 綠色（低佔用）
        elif occupancy_rate <= 70:
            color = "#ffd43b"  # 黃色（中等佔用）
        else:
            color = "#ff6b6b"  # 紅色（高佔用）

        st.markdown(
            f'<div style="text-align: center;">'
            f'<p style="font-size: 0.875rem; color: #666; margin-bottom: 0.25rem;">佔用率</p>'
            f'<p style="font-size: 2rem; font-weight: bold; color: {color}; margin: 0;">{occupancy_rate:.1f}%</p>'
            f'</div>',
            unsafe_allow_html=True
        )

    # 座位配置示意圖
    st.markdown("#### 座位配置圖")

    # 定義座位位置（根據圖片的相對位置）
    seat_positions = {
        # 窗邊座位（W1-W6）- 上方橫排
        'W1': (1, 5), 'W2': (2, 5), 'W3': (3, 5),
        'W4': (4, 5), 'W5': (5, 5), 'W6': (6, 5),

        # 窗邊座位（W7-W12）- 右側縱排
        'W7': (7, 4), 'W8': (7, 3), 'W9': (7, 2),
        'W10': (7, 1), 'W11': (7, 0), 'W12': (7, -1),

        # 四人桌（T1-T4）- 中央 2x2 排列
        'T1': (1.5, 2.5), 'T2': (4.5, 2.5),
        'T3': (1.5, 0), 'T4': (4.5, 0)
    }

    # 建立座位狀態列表
    seat_data = []
    for seat_id, (x, y) in seat_positions.items():
        status = df[df['seat_id'] == seat_id]['status'].values[0] if seat_id in df['seat_id'].values else 'available'
        is_occupied = (status == 'occupied')

        seat_data.append({
            'seat_id': seat_id,
            'x': x,
            'y': y,
            'status': '佔用' if is_occupied else '空位',
            'color': '#ff6b6b' if is_occupied else '#51cf66',
            'size': 80 if seat_id.startswith('T') else 40  # 四人桌較大
        })

    seat_df = pd.DataFrame(seat_data)

    # 使用 Plotly 繪製座位配置圖
    fig = go.Figure()

    # 添加座位標記
    for _, row in seat_df.iterrows():
        fig.add_trace(go.Scatter(
            x=[row['x']],
            y=[row['y']],
            mode='markers+text',
            marker=dict(
                size=row['size'],
                color=row['color'],
                line=dict(width=2, color='#333')
            ),
            text=f"{row['seat_id']}<br>{row['status']}",
            textposition='middle center',
            textfont=dict(size=10, color='white', family='Arial Black'),
            name=row['seat_id'],
            showlegend=False,
            hovertemplate=f"<b>{row['seat_id']}</b><br>狀態: {row['status']}<extra></extra>"
        ))

    # 添加門的位置標記（右下角）
    fig.add_annotation(
        x=7.5, y=-2,
        text="門",
        showarrow=False,
        font=dict(size=14, color='#666'),
        bordercolor="#666",
        borderwidth=2,
        borderpad=4,
        bgcolor="#f0f0f0"
    )

    # 添加窗的位置標記（上方）
    fig.add_annotation(
        x=3.5, y=5.8,
        text="窗",
        showarrow=False,
        font=dict(size=14, color='#666'),
        bordercolor="#666",
        borderwidth=2,
        borderpad=4,
        bgcolor="#f0f0f0"
    )

    # 設定圖表佈局
    fig.update_layout(
        height=500,
        xaxis=dict(
            range=[-0.5, 8.5],
            showgrid=False,
            zeroline=False,
            showticklabels=False
        ),
        yaxis=dict(
            range=[-2.5, 6.5],
            showgrid=False,
            zeroline=False,
            showticklabels=False
        ),
        plot_bgcolor='#f8f9fa',
        margin=dict(l=20, r=20, t=20, b=20),
        hovermode='closest'
    )

    st.plotly_chart(fig, width='stretch')

    # 圖例說明
    col_legend1, col_legend2 = st.columns(2)
    with col_legend1:
        st.markdown('<div style="background-color: #ff6b6b; color: white; padding: 10px; border-radius: 5px; text-align: center; font-weight: bold;">🔴 已佔用</div>', unsafe_allow_html=True)
    with col_legend2:
        st.markdown('<div style="background-color: #51cf66; color: white; padding: 10px; border-radius: 5px; text-align: center; font-weight: bold;">🟢 空位</div>', unsafe_allow_html=True)

    st.divider()

    # ============================================================
    # 本週人流統計區塊
    # ============================================================
    st.subheader("📈 本週人流統計")

    # 自動取得當前週次
    current_week = datetime.now().isocalendar()[1]

    # 讀取本週統計資料
    weekly_df, week_number = get_weekly_occupancy(current_week)

    if weekly_df is None or weekly_df.empty:
        st.info(f"ℹ️ 第 {current_week} 週尚無統計資料")
    else:
        st.caption(f"📅 第 {week_number} 週統計資料")

        # 計算每日平均
        daily_avg = weekly_df.groupby(['weekday', 'weekday_zh'])['avg_occupancy'].mean().reset_index()
        daily_avg = daily_avg.sort_values('weekday')

        # 每日平均佔用趨勢圖
        fig_daily = px.bar(
            daily_avg,
            x='weekday_zh',
            y='avg_occupancy',
            labels={'weekday_zh': '星期', 'avg_occupancy': '佔用數'},
            color='avg_occupancy',
            color_continuous_scale='RdYlGn_r',
            text='avg_occupancy'
        )
        fig_daily.update_traces(texttemplate='%{text:.1f}', textposition='outside')
        fig_daily.update_layout(
            showlegend=False,
            height=350,
            xaxis_title="星期",
            yaxis_title="佔用數"
        )
        st.plotly_chart(fig_daily, width='stretch')

    # 以較長間隔重新整理以降低對後端的負載
    import time
    time.sleep(10)
    st.rerun()


# ============================================================
# 主程式
# ============================================================

def main():
    # 初始化 Firebase
    if not initialize_firebase():
        st.stop()

    # 側邊欄
    st.sidebar.title("🪑 SeatLive")
    st.sidebar.markdown("---")
    st.sidebar.caption("© 2025 SeatLive - 餐廳座位監控系統")

    # 顯示主頁面（即時座位狀態 + 本週人流統計）
    display_seat_status_page()


if __name__ == "__main__":
    main()
