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
    initial_sidebar_state="collapsed"
)

# CSS 樣式
st.markdown("""
<style>
    /* 移除 Streamlit 預設邊距以適配手機 */
    .block-container {
        padding-top: 2rem;
        padding-bottom: 3rem;
        padding-left: 1rem;
        padding-right: 1rem;
        max-width: 100%;
    }

    /* 背景透明以適配深色模式 */
    .stApp {
        background: transparent;
    }

    .main-header {
        font-size: 2.5rem;
        font-weight: bold;
        color: #1f77b4;
        text-align: center;
        margin-bottom: 1.5rem;
        margin-top: 1rem;
        line-height: 1.2;
    }

    /* 手機端適配標題 */
    @media (max-width: 768px) {
        .main-header {
            font-size: 1.8rem;
            margin-bottom: 1rem;
        }
    }

    .metric-card {
        background-color: rgba(240, 242, 246, 0.5);
        padding: 1rem;
        border-radius: 0.5rem;
        text-align: center;
    }

    /* 強制 metric 數值和標籤置中 */
    [data-testid="stMetricValue"] {
        text-align: center !important;
        justify-content: center !important;
        display: flex !important;
        width: 100% !important;
    }

    [data-testid="stMetricLabel"] {
        text-align: center !important;
        justify-content: center !important;
        display: flex !important;
        width: 100% !important;
    }

    [data-testid="metric-container"] {
        text-align: center !important;
    }

    /* 底部版權資訊樣式 */
    .footer {
        text-align: center;
        color: #666;
        padding: 2rem 0 2rem 0;
        font-size: 0.875rem;
        border-top: 1px solid rgba(128, 128, 128, 0.2);
        margin-top: 3rem;
        margin-bottom: 0;
        width: 100%;
        clear: both;
    }

    /* 免責聲明樣式 */
    .disclaimer {
        text-align: center;
        color: #999;
        font-size: 0.75rem;
        padding: 0.5rem;
        margin-top: 1rem;
        font-style: italic;
    }

    /* 手機端適配 */
    @media (max-width: 768px) {
        .block-container {
            padding-left: 0.5rem;
            padding-right: 0.5rem;
            padding-bottom: 2rem;
        }

        .footer {
            font-size: 0.75rem;
            padding: 1.5rem 0 1.5rem 0;
        }
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
                # Streamlit Cloud 模式
                cred = credentials.Certificate(dict(st.secrets['firebase']))
                database_url = st.secrets['FIREBASE_DATABASE_URL']
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

            # 初始化 Firebase
            firebase_admin.initialize_app(cred, {
                'databaseURL': database_url
            })

        return True
    except Exception as e:
        st.error(f"❌ Firebase 初始化失敗: {e}")
        import traceback
        st.error(f"詳細錯誤：\n```\n{traceback.format_exc()}\n```")
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


def get_recent_daily_occupancy(days=8):
    """從 Firebase 讀取近 N 日的時段統計資料"""
    try:
        # 取得當前週次和前一週
        current_week = datetime.now().isocalendar()[1]
        weeks_to_fetch = [current_week, current_week - 1] if current_week > 1 else [current_week]

        all_data = []

        # 從可能的週次中取得資料
        for week_num in weeks_to_fetch:
            ref = db.reference(f'/occupancy_statistics/week_{week_num}')
            data = ref.get()

            if data and 'detail_data' in data:
                # 取得詳細的時段資料（非聚合資料）
                detail_df = pd.DataFrame(data['detail_data'])
                if not detail_df.empty:
                    all_data.append(detail_df)

        if not all_data:
            return None

        # 合併所有週次的資料
        combined_df = pd.concat(all_data, ignore_index=True)

        # 篩選近 N 日的資料
        if 'datetime' in combined_df.columns:
            combined_df['datetime'] = pd.to_datetime(combined_df['datetime'])
            cutoff_date = datetime.now() - pd.Timedelta(days=days)
            combined_df = combined_df[combined_df['datetime'] >= cutoff_date]
        elif 'date' in combined_df.columns:
            combined_df['date'] = pd.to_datetime(combined_df['date'])
            cutoff_date = datetime.now() - pd.Timedelta(days=days)
            combined_df = combined_df[combined_df['date'] >= cutoff_date]

        return combined_df if not combined_df.empty else None

    except Exception as e:
        st.error(f"❌ 讀取近日統計失敗: {e}")
        return None


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

    # 添加座位標記（改為矩形）
    for _, row in seat_df.iterrows():
        # 計算矩形大小
        rect_size = 0.4 if row['seat_id'].startswith('T') else 0.25
        font_size = 12 if row['seat_id'].startswith('T') else 10

        # 添加矩形背景
        fig.add_shape(
            type="rect",
            x0=row['x'] - rect_size, y0=row['y'] - rect_size,
            x1=row['x'] + rect_size, y1=row['y'] + rect_size,
            fillcolor=row['color'],
            line=dict(width=2, color='#333'),
        )

        # 只添加座位 ID 文字（白色），狀態用顏色表示
        fig.add_annotation(
            x=row['x'],
            y=row['y'],
            text=row['seat_id'],
            font=dict(size=font_size, color='white', family='Arial Black'),
            showarrow=False,
            xanchor='center',
            yanchor='middle'
        )

        # 添加隱形的 hover 點
        fig.add_trace(go.Scatter(
            x=[row['x']],
            y=[row['y']],
            mode='markers',
            marker=dict(size=1, opacity=0),
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

    # 設定圖表佈局（鎖定不可拖拉或縮放）
    fig.update_layout(
        height=500,
        xaxis=dict(
            range=[-0.5, 8.5],
            showgrid=False,
            zeroline=False,
            showticklabels=False,
            fixedrange=True  # 鎖定 X 軸
        ),
        yaxis=dict(
            range=[-2.5, 6.5],
            showgrid=False,
            zeroline=False,
            showticklabels=False,
            fixedrange=True  # 鎖定 Y 軸
        ),
        plot_bgcolor='rgba(248, 249, 250, 0.5)',
        margin=dict(l=20, r=20, t=20, b=20),
        hovermode='closest',
        dragmode=False  # 禁用拖拉
    )

    st.plotly_chart(fig, width='stretch', config={'displayModeBar': False})

    # 圖例說明
    col_legend1, col_legend2 = st.columns(2)
    with col_legend1:
        st.markdown('<div style="background-color: #ff6b6b; color: white; padding: 10px; border-radius: 5px; text-align: center; font-weight: bold;">🔴 已佔用</div>', unsafe_allow_html=True)
    with col_legend2:
        st.markdown('<div style="background-color: #51cf66; color: white; padding: 10px; border-radius: 5px; text-align: center; font-weight: bold;">🟢 空位</div>', unsafe_allow_html=True)

    # 免責聲明
    st.markdown('<div class="disclaimer">⚠️ 因延遲及辨識準確性，即時狀態僅供參考，請以實際現場狀況為主</div>', unsafe_allow_html=True)

    st.divider()

    # ============================================================
    # 近日人流統計區塊
    # ============================================================
    st.subheader("📈 近日人流統計")

    # 讀取近 8 日的時段統計資料
    recent_df = get_recent_daily_occupancy(days=8)

    if recent_df is None or recent_df.empty:
        st.info("ℹ️ 近 8 日尚無統計資料")
    else:
        # 確保有日期欄位
        if 'datetime' in recent_df.columns:
            recent_df['date'] = pd.to_datetime(recent_df['datetime']).dt.date
        elif 'date' in recent_df.columns:
            recent_df['date'] = pd.to_datetime(recent_df['date']).dt.date

        # 取得唯一的日期並排序（由新到舊）
        unique_dates = sorted(recent_df['date'].unique(), reverse=True)

        if len(unique_dates) == 0:
            st.info("ℹ️ 近 8 日尚無統計資料")
        else:
            st.caption(f"📅 顯示近 {len(unique_dates)} 日資料（最新日期在上方）")

            # 為每一天繪製時段分布圖
            for date in unique_dates:
                # 篩選該日期的資料
                day_df = recent_df[recent_df['date'] == date].copy()

                if day_df.empty:
                    continue

                # 提取時間（小時）
                if 'time' in day_df.columns:
                    day_df['hour'] = day_df['time'].str.split(':').str[0].astype(int)
                elif 'datetime' in day_df.columns:
                    day_df['hour'] = pd.to_datetime(day_df['datetime']).dt.hour

                # 按小時聚合（取平均）
                hourly_data = day_df.groupby('hour')['occupancy_count'].mean().reset_index()

                # 顯示日期標題（包含星期幾）
                weekday_name = ['週一', '週二', '週三', '週四', '週五', '週六', '週日'][date.weekday()]
                st.markdown(f"**{date.strftime('%Y-%m-%d')} ({weekday_name})**")

                # 繪製膠囊圖（類似圖片範例）
                fig = go.Figure()

                # 找出最大佔用數以標準化高度
                max_occupancy = hourly_data['occupancy_count'].max() if not hourly_data.empty else 1

                for _, row in hourly_data.iterrows():
                    hour = row['hour']
                    occupancy = row['occupancy_count']

                    # 計算膠囊高度（標準化）
                    height = (occupancy / max_occupancy) * 0.8 if max_occupancy > 0 else 0

                    # 決定顏色（根據佔用率）
                    if occupancy >= max_occupancy * 0.8:
                        color = '#d946a6'  # 高峰時段（粉紅色）
                    elif occupancy >= max_occupancy * 0.5:
                        color = '#94a3b8'  # 中等時段（灰藍色）
                    else:
                        color = '#94a3b8'  # 低峰時段（灰藍色）

                    # 繪製膠囊形狀（圓角矩形）
                    fig.add_shape(
                        type="rect",
                        x0=hour - 0.3, x1=hour + 0.3,
                        y0=0, y1=height,
                        fillcolor=color,
                        line=dict(width=0),
                        opacity=0.8
                    )

                    # 顯示數值（在膠囊上方）
                    if occupancy > 0:
                        fig.add_annotation(
                            x=hour,
                            y=height + 0.05,
                            text=f"{occupancy:.0f}",
                            showarrow=False,
                            font=dict(size=9, color='#666'),
                            yanchor='bottom'
                        )

                # 設定圖表佈局
                fig.update_layout(
                    height=150,
                    xaxis=dict(
                        tickmode='linear',
                        tick0=0,
                        dtick=3,
                        tickformat='%H時',
                        tickvals=list(range(0, 24, 3)),
                        ticktext=[f"{h}時" for h in range(0, 24, 3)],
                        range=[-1, 24],
                        showgrid=False,
                        fixedrange=True
                    ),
                    yaxis=dict(
                        showticklabels=False,
                        showgrid=False,
                        range=[0, 1],
                        fixedrange=True
                    ),
                    margin=dict(l=10, r=10, t=10, b=30),
                    plot_bgcolor='rgba(0,0,0,0)',
                    paper_bgcolor='rgba(0,0,0,0)',
                    dragmode=False,
                    hovermode=False
                )

                st.plotly_chart(fig, width='stretch', config={'displayModeBar': False}, key=f"daily_{date}")

    # 不在這裡自動重新整理，改到 main() 函數最後


# ============================================================
# 主程式
# ============================================================

def main():
    # 初始化 Firebase
    if not initialize_firebase():
        st.stop()

    # 顯示主頁面（即時座位狀態 + 近日人流統計）
    display_seat_status_page()

    # 底部版權資訊（只顯示一次）
    st.markdown('<div class="footer">© 2025 SeatLive - 餐廳座位監控系統</div>', unsafe_allow_html=True)

    # 每 5 秒自動重新整理（使用倒數計時避免閃爍）
    import time
    time.sleep(5)
    st.rerun()


if __name__ == "__main__":
    main()
