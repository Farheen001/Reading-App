import streamlit as st
import pandas as pd
import plotly.express as px
from datetime import datetime
import PyPDF2
import time
import fitz
from PIL import Image
import io
import os
import json
import hashlib

st.set_page_config(page_title="📚 ReadVibe", page_icon="📚", layout="wide")

# Colors
COLORS = {
    'primary': '#FF6B9D',
    'secondary': '#00D9FF',
    'accent': '#B366FF',
    'success': '#00FF88',
    'warning': '#FFD700',
}

# CSS
st.markdown(f"""
    <style>
    @import url('https://fonts.googleapis.com/css2?family=Poppins:wght@600;700;800&display=swap');
    * {{ font-family: 'Poppins', sans-serif; }}
    
    [data-testid="stAppViewContainer"] {{ 
        background: linear-gradient(135deg, #0A0E27 0%, #1a1f3a 100%);
    }}
    
    .header {{ text-align: center; font-size: 3em; font-weight: 800; 
              background: linear-gradient(135deg, {COLORS['primary']} 0%, {COLORS['secondary']} 100%);
              -webkit-background-clip: text; -webkit-text-fill-color: transparent; }}
    
    .card {{ background: rgba(255, 107, 157, 0.1); border-radius: 15px; padding: 20px; 
            border: 1px solid rgba(255, 107, 157, 0.2); backdrop-filter: blur(10px);
            margin: 10px 0; transition: all 0.3s; }}
    
    .card:hover {{ transform: translateY(-5px); box-shadow: 0 10px 30px rgba(255, 107, 157, 0.3); }}
    
    .metric {{ font-size: 2.5em; font-weight: 800; 
              background: linear-gradient(135deg, {COLORS['primary']} 0%, {COLORS['secondary']} 100%);
              -webkit-background-clip: text; -webkit-text-fill-color: transparent; }}
    
    .label {{ color: {COLORS['secondary']}; font-weight: 600; text-transform: uppercase; font-size: 0.9em; }}
    
    .progress {{ background: rgba(0,0,0,0.3); border-radius: 10px; height: 12px; overflow: hidden; 
                 border: 1px solid rgba(255,107,157,0.2); margin: 10px 0; }}
    
    .progress-bar {{ background: linear-gradient(90deg, {COLORS['primary']} 0%, {COLORS['secondary']} 100%);
                     height: 100%; border-radius: 10px; transition: width 0.5s; }}
    
    .badge {{ display: inline-block; background: linear-gradient(135deg, {COLORS['primary']} 0%, {COLORS['secondary']} 100%);
              color: white; padding: 6px 12px; border-radius: 20px; font-size: 0.8em; font-weight: 700; }}
    
    h1, h2, h3, h4, h5, h6 {{ color: #ffffff !important; text-shadow: 0 2px 4px rgba(0,0,0,0.5); }}
    p {{ color: #ffffff !important; }}
    span {{ color: #ffffff !important; }}
    div {{ color: #ffffff !important; }}
    
    .stMarkdown {{ color: #ffffff !important; }}
    [data-testid="stMarkdownContainer"] {{ color: #ffffff !important; }}
    
    .stButton > button {{ background: linear-gradient(135deg, {COLORS['primary']} 0%, {COLORS['accent']} 100%);
                          color: white; border: none; border-radius: 10px; font-weight: 700;
                          text-transform: uppercase; letter-spacing: 1px; }}
    
    [data-testid="stSidebar"] {{ background: rgba(255, 107, 157, 0.08) !important; }}
    
    label {{ color: #ffffff !important; }}
    .stTextInput input {{ color: #ffffff !important; }}
    .stNumberInput input {{ color: #ffffff !important; }}
    .stSelectbox select {{ color: #ffffff !important; }}
    input {{ color: #ffffff !important; }}
    select {{ color: #ffffff !important; }}
    </style>
""", unsafe_allow_html=True)

# Initialize session state
if 'books' not in st.session_state:
    st.session_state.books = []

if 'stats' not in st.session_state:
    st.session_state.stats = {
        'total_pages': 0,
        'total_time': 0,
        'points': 0,
        'weekly_pages': 0,
        'monthly_pages': 0,
    }

if 'pdf_page' not in st.session_state:
    st.session_state.pdf_page = 0

if 'reader_pdf_page' not in st.session_state:
    st.session_state.reader_pdf_page = 0

# Data file for storing users and their data
DATA_FILE = os.path.join(os.path.dirname(__file__), 'users.json')
DATA_DIR = os.path.join(os.path.dirname(__file__), 'data')

if not os.path.exists(DATA_DIR):
    try:
        os.makedirs(DATA_DIR, exist_ok=True)
    except Exception:
        pass

def load_users():
    try:
        if os.path.exists(DATA_FILE):
            with open(DATA_FILE, 'r', encoding='utf-8') as f:
                return json.load(f)
    except Exception:
        pass
    return {}

def save_users(users):
    try:
        with open(DATA_FILE, 'w', encoding='utf-8') as f:
            json.dump(users, f, ensure_ascii=False, indent=2)
    except Exception as e:
        st.error(f"Failed saving user data: {e}")


def migrate_users_db(users: dict) -> dict:
    """Migrate any in-memory stored PDFs or PIL images into on-disk files and update book entries.
    This makes the users JSON serializable and prevents errors from raw bytes or PIL objects.
    """
    try:
        changed = False
        for uname, urec in list(users.items()):
            if uname == '_last_user':
                continue
            data = urec.get('data', {}) if isinstance(urec, dict) else {}
            books = data.get('books', [])
            if not books:
                continue
            # ensure user dir
            user_folder_name = ''.join(c for c in uname if c.isalnum() or c in ('-', '_'))
            user_dir = os.path.join(DATA_DIR, user_folder_name)
            os.makedirs(user_dir, exist_ok=True)

            new_books = []
            seen_paths = set()
            for b in books:
                # if already stored as paths, keep
                if b.get('pdf_path') and isinstance(b.get('pdf_path'), str) and os.path.exists(b.get('pdf_path')):
                    new_books.append(b)
                    continue

                # migrate pdf bytes if present
                pdf_path = b.get('pdf_path')
                if not pdf_path and b.get('pdf_file'):
                    try:
                        ts = int(time.time())
                        safe_title = ''.join(c for c in (b.get('title') or 'book') if c.isalnum() or c in (' ', '-', '_')).replace(' ', '_')[:120]
                        pdf_filename = f"{safe_title}_{ts}.pdf"
                        pdf_path = os.path.join(user_dir, pdf_filename)
                        with open(pdf_path, 'wb') as f:
                            f.write(b.get('pdf_file'))
                        changed = True
                    except Exception:
                        pdf_path = None

                # migrate cover if present or generate from pdf
                cover_path = b.get('cover_path')
                if not cover_path:
                    cover_saved = False
                    if b.get('cover_image'):
                        try:
                            ts = int(time.time())
                            safe_title = ''.join(c for c in (b.get('title') or 'book') if c.isalnum() or c in (' ', '-', '_')).replace(' ', '_')[:120]
                            cover_filename = f"{safe_title}_{ts}.png"
                            cover_path = os.path.join(user_dir, cover_filename)
                            img = b.get('cover_image')
                            # PIL Image -> save
                            try:
                                img.save(cover_path)
                                cover_saved = True
                                changed = True
                            except Exception:
                                cover_path = None
                        except Exception:
                            cover_path = None

                    # try generating from pdf path
                    if not cover_saved and pdf_path and os.path.exists(pdf_path):
                        try:
                            img = get_pdf_first_page_image(pdf_path)
                            if img:
                                ts = int(time.time())
                                safe_title = ''.join(c for c in (b.get('title') or 'book') if c.isalnum() or c in (' ', '-', '_')).replace(' ', '_')[:120]
                                cover_filename = f"{safe_title}_{ts}.png"
                                cover_path = os.path.join(user_dir, cover_filename)
                                try:
                                    img.save(cover_path)
                                    changed = True
                                except Exception:
                                    cover_path = None
                        except Exception:
                            cover_path = None

                # skip duplicates by pdf path
                if pdf_path and pdf_path in seen_paths:
                    continue

                new_b = {
                    'title': b.get('title'),
                    'author': b.get('author'),
                    'pages': b.get('pages'),
                    'current_page': b.get('current_page', 0),
                    'pages_read': b.get('pages_read', 0),
                    'pdf_path': pdf_path,
                    'cover_path': cover_path,
                }
                new_books.append(new_b)
                if pdf_path:
                    seen_paths.add(pdf_path)

            if changed:
                data['books'] = new_books
                urec['data'] = data
                users[uname] = urec
        if changed:
            try:
                with open(DATA_FILE, 'w', encoding='utf-8') as f:
                    json.dump(users, f, ensure_ascii=False, indent=2)
            except Exception:
                pass
    except Exception:
        pass
    return users

def hash_password(pw: str) -> str:
    return hashlib.sha256(pw.encode('utf-8')).hexdigest()

# Load users DB into session
if 'users_db' not in st.session_state:
    loaded = load_users()
    # migrate any old in-memory PDFs or images to on-disk files
    migrated = migrate_users_db(loaded)
    st.session_state.users_db = migrated

if 'current_user' not in st.session_state:
    st.session_state.current_user = None

# If a user was last active, restore them and load their data so login persists across refresh
try:
    last_user = st.session_state.users_db.get('_last_user') if isinstance(st.session_state.users_db, dict) else None
    if last_user and st.session_state.current_user is None and last_user in st.session_state.users_db:
        st.session_state.current_user = last_user
        data = st.session_state.users_db[last_user].get('data', {})
        st.session_state.books = data.get('books', [])
        st.session_state.stats = data.get('stats', st.session_state.stats)
except Exception:
    pass

def extract_pdf_pages(pdf_bytes):
    try:
        # pdf_bytes may be a path or raw bytes
        if isinstance(pdf_bytes, (bytes, bytearray)):
            doc = fitz.open(stream=pdf_bytes, filetype="pdf")
        elif isinstance(pdf_bytes, str) and os.path.exists(pdf_bytes):
            doc = fitz.open(pdf_bytes)
        else:
            return None
        return len(doc)
    except:
        return None

def get_pdf_first_page_image(pdf_bytes):
    """Extract first page of PDF as image"""
    try:
        if isinstance(pdf_bytes, (bytes, bytearray)):
            doc = fitz.open(stream=pdf_bytes, filetype="pdf")
        elif isinstance(pdf_bytes, str) and os.path.exists(pdf_bytes):
            doc = fitz.open(pdf_bytes)
        else:
            return None
        page = doc[0]
        pix = page.get_pixmap(matrix=fitz.Matrix(2, 2))  # 2x zoom for better quality
        img_bytes = pix.tobytes("png")
        return Image.open(io.BytesIO(img_bytes))
    except:
        pass
    return None

def get_pdf_page_image(pdf_bytes, page_num):
    """Extract a specific page of PDF as image"""
    try:
        if isinstance(pdf_bytes, (bytes, bytearray)):
            doc = fitz.open(stream=pdf_bytes, filetype="pdf")
        elif isinstance(pdf_bytes, str) and os.path.exists(pdf_bytes):
            doc = fitz.open(pdf_bytes)
        else:
            return None
        if page_num >= len(doc):
            page_num = len(doc) - 1
        page = doc[page_num]
        pix = page.get_pixmap(matrix=fitz.Matrix(2, 2))
        img_bytes = pix.tobytes("png")
        return Image.open(io.BytesIO(img_bytes))
    except:
        pass
    return None

def estimate_read_time(pdf_bytes, page_num, reader_wpm=None):
    """Estimate reading time (minutes) for a specific page using text extraction and heuristics."""
    try:
        if isinstance(pdf_bytes, (bytes, bytearray)):
            doc = fitz.open(stream=pdf_bytes, filetype="pdf")
        elif isinstance(pdf_bytes, str) and os.path.exists(pdf_bytes):
            doc = fitz.open(pdf_bytes)
        else:
            return None
        if page_num >= len(doc):
            page_num = len(doc) - 1
        page = doc[page_num]
        text = page.get_text("text") or ""
        words = [w for w in text.split() if w.isalpha() or w.isalnum()]
        word_count = len(words)
        if word_count == 0:
            return 0.1  # very short

        # base reading speed
        base_wpm = reader_wpm or 200

        # difficulty adjustments: long words slow reading
        avg_len = sum(len(w) for w in words) / max(1, word_count)
        long_ratio = sum(1 for w in words if len(w) > 7) / word_count
        difficulty_factor = 1 + (long_ratio * 0.35) + max(0, (avg_len - 5) / 10)

        minutes = (word_count / base_wpm) * difficulty_factor
        return minutes
    except Exception:
        return None

def is_realistic(book_pdf_path, start_page, end_page, minutes, user_wpm=None):
    """Validate reading speed by estimating time for the range and comparing to actual time spent.
    Uses word count estimation for more accuracy.
    """
    if minutes < 1:
        return False
    try:
        # Estimate total time for reading this page range
        total_estimated_minutes = 0
        for page_num in range(start_page, min(end_page, end_page)):
            est = estimate_read_time(book_pdf_path, page_num, reader_wpm=user_wpm)
            if est:
                total_estimated_minutes += est
        
        if total_estimated_minutes == 0:
            return True  # fallback if estimation fails
        
        # Check if actual time is within reasonable bounds (1x to 3x estimated time)
        # This allows for slower reading, breaks, and distractions
        ratio = minutes / total_estimated_minutes
        return 1.0 <= ratio <= 3.0
    except Exception:
        # Fallback to simple speed check if word-count estimation fails
        if minutes < 2:
            return False
        speed = (end_page - start_page) / minutes
        return 0.3 <= speed <= 0.7

def calc_points(pages, minutes):
    points = (pages // 10) * 5
    if minutes >= 20: points += 15
    elif minutes >= 10: points += 8
    if minutes >= 30: points += 20
    return points

# Sidebar
with st.sidebar:
    st.markdown(f"<h1 style='text-align: center; color: {COLORS['primary']}; font-size: 2.5em;'>📚 ReadVibe</h1>", unsafe_allow_html=True)
    st.divider()
    # Account section
    if st.session_state.current_user:
        st.markdown(f"<div style='text-align:center; padding:6px;'>👋 <strong>{st.session_state.current_user}</strong></div>", unsafe_allow_html=True)
        if st.button("Logout", key="logout_btn"):
            st.session_state.current_user = None
            # reset session view
            st.session_state.books = []
            st.session_state.stats = {
                'total_pages': 0,
                'total_time': 0,
                'points': 0,
                'weekly_pages': 0,
                'monthly_pages': 0,
            }
            # clear last user marker
            try:
                users = st.session_state.users_db
                if isinstance(users, dict) and users.get('_last_user'):
                    users['_last_user'] = None
                    save_users(users)
                    st.session_state.users_db = users
            except Exception:
                pass
            st.rerun()
    else:
        acct_mode = st.radio("Account", ["Login", "Sign Up"], index=0)
        if acct_mode == "Login":
            login_user = st.text_input("Username", key="login_user")
            login_pw = st.text_input("Password", type="password", key="login_pw")
            if st.button("Login", key="do_login"):
                users = st.session_state.users_db
                if login_user in users and users[login_user].get('password') == hash_password(login_pw):
                    st.session_state.current_user = login_user
                    # load user data
                    data = users[login_user].get('data', {})
                    st.session_state.books = data.get('books', [])
                    st.session_state.stats = data.get('stats', st.session_state.stats)
                    st.success("Logged in")
                    # remember last user for persistent login
                    try:
                        users['_last_user'] = login_user
                        save_users(users)
                        st.session_state.users_db = users
                    except Exception:
                        pass
                    st.rerun()
                else:
                    st.error("Invalid credentials")
        else:
            signup_user = st.text_input("New username", key="signup_user")
            signup_pw = st.text_input("New password", type="password", key="signup_pw")
            if st.button("Create account", key="do_signup"):
                users = st.session_state.users_db
                if not signup_user:
                    st.error("Choose a username")
                elif signup_user in users:
                    st.error("Username already exists")
                else:
                    users[signup_user] = {
                        'password': hash_password(signup_pw),
                        'data': {
                            'books': [],
                            'stats': {
                                'total_pages': 0,
                                'total_time': 0,
                                'points': 0,
                                'weekly_pages': 0,
                                'monthly_pages': 0,
                            }
                        }
                    }
                    save_users(users)
                    st.session_state.users_db = users
                    st.success("Account created. Please log in.")
    st.divider()
    page = st.radio("Navigation", ["🏠 Home", "📖 Read", "📚 Library", "📊 Stats", "🎁 Rewards", "⚙️ Settings"], label_visibility="collapsed")

# ==================== HOME ====================
if page == "🏠 Home":
    st.markdown(f"<div class='header'>📚 ReadVibe</div>", unsafe_allow_html=True)
    st.markdown(f"<p style='text-align: center; color: {COLORS['secondary']}; font-size: 1.1em;'>Your Reading Journey ✨</p>", unsafe_allow_html=True)
    st.divider()
    
    col1, col2, col3, col4 = st.columns(4)
    with col1:
        st.markdown(f"<div class='card'><div class='label'>Pages Today</div><div class='metric'>{st.session_state.stats['total_pages'] % 30}</div></div>", unsafe_allow_html=True)
    with col2:
        st.markdown(f"<div class='card'><div class='label'>Points</div><div class='metric'>{st.session_state.stats['points']}</div></div>", unsafe_allow_html=True)
    with col3:
        st.markdown(f"<div class='card'><div class='label'>Books</div><div class='metric'>{len(st.session_state.books)}</div></div>", unsafe_allow_html=True)
    with col4:
        st.markdown(f"<div class='card'><div class='label'>Time</div><div class='metric'>{st.session_state.stats['total_time']}</div><div class='label'>mins</div></div>", unsafe_allow_html=True)
    
    st.divider()
    
    # Load user goals
    home_daily_goal = 30
    home_monthly_goal = 800
    if st.session_state.current_user:
        try:
            user_rec = st.session_state.users_db.get(st.session_state.current_user, {})
            goals = user_rec.get('data', {}).get('goals', {})
            home_daily_goal = goals.get('daily', 30)
            home_monthly_goal = goals.get('monthly', 800)
        except Exception:
            pass
    
    col1, col2 = st.columns(2)
    with col1:
        daily = st.session_state.stats['total_pages'] % home_daily_goal
        daily_pct = min((daily / home_daily_goal) * 100, 100)
        st.markdown(f"""
            <div class='card'>
                <div style='display: flex; justify-content: space-between; margin-bottom: 10px;'>
                    <span class='label'>Daily Goal</span>
                    <span style='color: {COLORS['primary']}; font-weight: 800;'>{int(daily_pct)}%</span>
                </div>
                <div class='progress'><div class='progress-bar' style='width: {daily_pct}%;'></div></div>
                <div class='label' style='margin-top: 10px;'>{daily}/{home_daily_goal} pages</div>
            </div>
        """, unsafe_allow_html=True)
    
    with col2:
        monthly = st.session_state.stats['monthly_pages']
        monthly_pct = min((monthly / home_monthly_goal) * 100, 100)
        st.markdown(f"""
            <div class='card'>
                <div style='display: flex; justify-content: space-between; margin-bottom: 10px;'>
                    <span class='label'>Monthly Goal</span>
                    <span style='color: {COLORS['secondary']}; font-weight: 800;'>{int(monthly_pct)}%</span>
                </div>
                <div class='progress'><div class='progress-bar' style='width: {monthly_pct}%;'></div></div>
                <div class='label' style='margin-top: 10px;'>{monthly}/{home_monthly_goal} pages</div>
            </div>
        """, unsafe_allow_html=True)

# ==================== READER ====================
elif page == "📖 Read":
    st.markdown(f"<div class='header'>📖 Ebook Reader</div>", unsafe_allow_html=True)
    st.divider()
    
    if not st.session_state.books:
        st.info("📚 No books uploaded yet! Go to Library to add one.")
    else:
        book_idx = st.selectbox("Select Book", range(len(st.session_state.books)), 
                                format_func=lambda x: st.session_state.books[x]['title'], label_visibility="collapsed")
        book = st.session_state.books[book_idx]
        
        # Top controls
        col1, col2, col3, col4 = st.columns([1.5, 1, 1, 1.5])
        with col1:
            st.markdown(f"<h3 style='color: {COLORS['primary']}; margin: 0;'>{book['title']}</h3>", unsafe_allow_html=True)
        with col2:
            st.markdown(f"<div style='text-align: center; padding: 8px; background: rgba(255,107,157,0.2); border-radius: 8px;'><span style='color: {COLORS['secondary']};'>By</span> {book['author']}</div>", unsafe_allow_html=True)
        with col3:
            progress = (book.get('current_page', 0) / book['pages']) * 100
            st.markdown(f"<div style='text-align: center; padding: 8px; background: rgba(0,217,255,0.2); border-radius: 8px;'><span style='color: {COLORS['success']};'>{int(progress)}%</span></div>", unsafe_allow_html=True)
        with col4:
            st.markdown(f"<div style='text-align: center; padding: 8px; background: rgba(179,102,255,0.2); border-radius: 8px;'><span style='color: {COLORS['accent']};'>{book.get('current_page', 0)}/{book['pages']}</span></div>", unsafe_allow_html=True)
        
        st.divider()
        
        # PDF Viewer
        try:
            with st.spinner("⏳ Loading PDF..."):
                total_pages = extract_pdf_pages(book.get('pdf_path'))

            if total_pages is None:
                st.error("❌ Could not load PDF. Please check the file.")
            else:
                # Initialize pdf viewer page if needed
                if 'reader_pdf_page' not in st.session_state:
                    st.session_state.reader_pdf_page = book.get('current_page', 0)

                if 'reading_start_time' not in st.session_state:
                    st.session_state.reading_start_time = datetime.now()

                # Page slider
                st.markdown("<h4 style='margin-bottom: 10px; color: #ffffff;'>📄 Page Navigation</h4>", unsafe_allow_html=True)
                page_num = st.slider("Page", 1, total_pages, st.session_state.reader_pdf_page + 1, label_visibility="collapsed") - 1
                st.session_state.reader_pdf_page = page_num

                # Display PDF page
                with st.spinner("📖 Rendering page..."):
                    pdf_page_img = get_pdf_page_image(book.get('pdf_path'), page_num)

                if pdf_page_img:
                    st.markdown(f"<div style='background: rgba(255,107,157,0.08); border-radius: 10px; padding: 15px; border: 2px solid rgba(255,107,157,0.3);'>", unsafe_allow_html=True)
                    st.image(pdf_page_img, use_container_width=True, caption=f"Page {page_num + 1} of {total_pages}")
                    # Show AI-based estimated reading time for this page
                    est_minutes = None
                    try:
                        user_wpm = None
                        if st.session_state.current_user:
                            user_rec = st.session_state.users_db.get(st.session_state.current_user, {})
                            user_wpm = user_rec.get('data', {}).get('wpm')
                        est_minutes = estimate_read_time(book.get('pdf_path'), page_num, reader_wpm=user_wpm)
                    except Exception:
                        est_minutes = None

                    if est_minutes is not None:
                        mins_display = f"~{max(0.1, est_minutes):.1f} mins"
                        st.markdown(f"<div style='margin-top:8px; display:flex; gap:10px; align-items:center;'><div style='padding:8px 12px; background: rgba(0,217,255,0.08); border-radius:8px;'><strong style='color: {COLORS['secondary']}'>Estimated Read</strong><div style='color:#ffffff; font-weight:700;'>{mins_display}</div></div></div>", unsafe_allow_html=True)
                    st.markdown("</div>", unsafe_allow_html=True)
                else:
                    st.error("Could not render page. Try another page.")

                # Page info and controls
                col1, col2, col3, col4, col5 = st.columns(5)

                with col1:
                    if st.button("⏮️ First", use_container_width=True):
                        st.session_state.reader_pdf_page = 0
                        st.rerun()

                with col2:
                    if st.button("⬅️ Previous", use_container_width=True):
                        st.session_state.reader_pdf_page = max(0, st.session_state.reader_pdf_page - 1)
                        st.rerun()

                with col3:
                    st.markdown(f"<div style='text-align: center; padding: 12px; background: rgba(179,102,255,0.2); border-radius: 8px; border: 1px solid rgba(179,102,255,0.5);'><span style='color: #ffffff; font-weight: 700;'>Page {page_num + 1}/{total_pages}</span></div>", unsafe_allow_html=True)

                with col4:
                    if st.button("Next ➡️", use_container_width=True):
                        st.session_state.reader_pdf_page = min(total_pages - 1, st.session_state.reader_pdf_page + 1)
                        st.rerun()

                with col5:
                    if st.button("Last ⏭️", use_container_width=True):
                        st.session_state.reader_pdf_page = total_pages - 1
                        st.rerun()

                st.divider()

                # Reading session logger with scroll-based tracking
                st.markdown("<h4 style='margin-bottom: 15px; color: #ffffff;'>📝 Reading Session</h4>", unsafe_allow_html=True)

                # Auto-calculate reading time based on scroll
                if 'reading_start_time' in st.session_state:
                    elapsed_time = (datetime.now() - st.session_state.reading_start_time).total_seconds() / 60
                else:
                    elapsed_time = 0

                col1, col2, col3 = st.columns(3)
                with col1:
                    st.markdown(f"<div class='card'><div class='label'>Current Page</div><div class='metric'>{page_num + 1}</div></div>", unsafe_allow_html=True)
                with col2:
                    st.markdown(f"<div class='card'><div class='label'>Pages Scrolled</div><div class='metric'>{abs(page_num - book.get('current_page', 0))}</div></div>", unsafe_allow_html=True)
                with col3:
                    st.markdown(f"<div class='card'><div class='label'>Time Elapsed</div><div class='metric'>{int(elapsed_time)}</div><div class='label'>mins</div></div>", unsafe_allow_html=True)

                st.divider()

                col1, col2, col3 = st.columns(3)
                with col1:
                    start_page = st.number_input("Start Page", 1, book['pages'], max(1, book.get('current_page', 0)), key="start_log", label_visibility="collapsed")
                with col2:
                    end_page = st.number_input("End Page", start_page, book['pages'], min(page_num + 1, book['pages']), key="end_log", label_visibility="collapsed")
                with col3:
                    minutes = st.number_input("Minutes Spent", 1, 480, max(1, int(elapsed_time)), key="minutes_log", label_visibility="collapsed")

                pages_read = end_page - start_page

                col1, col2 = st.columns(2)
                with col1:
                    if pages_read > 0 and minutes > 0:
                        # Get user's WPM for realistic speed check
                        user_wpm = None
                        if st.session_state.current_user:
                            try:
                                user_rec = st.session_state.users_db.get(st.session_state.current_user, {})
                                user_wpm = user_rec.get('data', {}).get('wpm')
                            except Exception:
                                pass
                        
                        realistic = is_realistic(book.get('pdf_path'), start_page - 1, end_page, minutes, user_wpm=user_wpm)
                        if realistic:
                            st.success(f"✅ Realistic reading pace", icon="✅")
                        else:
                            st.error(f"⚠️ Reading time seems inconsistent with page content. Check your input.", icon="⚠️")

                with col2:
                    if pages_read > 0 and minutes > 0:
                        points = calc_points(pages_read, minutes)
                        st.metric("💎 Points Earned", points)

                if st.button("✅ Log & Update", use_container_width=True, key="log_session"):
                    if not st.session_state.current_user:
                        st.error("Please log in to save your reading sessions.")
                    else:
                        if pages_read > 0 and minutes > 0:
                            # Get user's WPM for validation
                            user_wpm = None
                            try:
                                user_rec = st.session_state.users_db.get(st.session_state.current_user, {})
                                user_wpm = user_rec.get('data', {}).get('wpm')
                            except Exception:
                                pass
                            
                            if is_realistic(book.get('pdf_path'), start_page - 1, end_page, minutes, user_wpm=user_wpm):
                                points = calc_points(pages_read, minutes)
                                st.session_state.stats['total_pages'] += pages_read
                                st.session_state.stats['total_time'] += minutes
                                st.session_state.stats['points'] += points
                                st.session_state.stats['weekly_pages'] += pages_read
                                st.session_state.stats['monthly_pages'] += pages_read
                                st.session_state.books[book_idx]['current_page'] = end_page
                                st.session_state.books[book_idx]['pages_read'] = st.session_state.books[book_idx].get('pages_read', 0) + pages_read
                                # persist to user DB
                                users = st.session_state.users_db
                                user = users.get(st.session_state.current_user, {})
                                data = user.get('data', {})
                                data['stats'] = st.session_state.stats
                                data['books'] = st.session_state.books
                                user['data'] = data
                                users[st.session_state.current_user] = user
                                save_users(users)
                                st.session_state.users_db = users

                                st.success(f"🎉 +{points} points! Great reading session!", icon="🎉")
                                st.balloons()
                                time.sleep(2)
                                st.rerun()
                            else:
                                st.error("⚠️ Reading speed seems too fast! Please check your input.", icon="⚠️")
        except Exception as e:
            st.error(f"❌ Error loading PDF: {str(e)}")

# ==================== LIBRARY ====================
elif page == "📚 Library":
    st.markdown(f"<div class='header'>📚 Library</div>", unsafe_allow_html=True)
    st.divider()
    
    st.markdown("### 📤 Upload PDF")
    uploaded = st.file_uploader("Choose PDF", type="pdf", key="uploader", help="Upload a PDF file")
    
    if uploaded:
        col1, col2 = st.columns([3, 1])
        with col1:
            title = st.text_input("Title", uploaded.name.replace('.pdf', ''), label_visibility="collapsed")
        with col2:
            author = st.text_input("Author", "Unknown", label_visibility="collapsed")
        
        if st.button("Add Book", use_container_width=True):
            if not st.session_state.current_user:
                st.error("Please create an account or log in to save books.")
            else:
                try:
                    # Read PDF once and reuse
                    pdf_bytes = uploaded.read()
                    pages = extract_pdf_pages(pdf_bytes)
                    
                    if pages:
                        # Save PDF and cover to disk (per-user folder)
                        user_folder_name = ''.join(c for c in st.session_state.current_user if c.isalnum() or c in ('-', '_'))
                        user_dir = os.path.join(DATA_DIR, user_folder_name)
                        os.makedirs(user_dir, exist_ok=True)
                        ts = int(time.time())
                        safe_title = ''.join(c for c in title if c.isalnum() or c in (' ', '-', '_')).replace(' ', '_')[:120]
                        pdf_filename = f"{safe_title}_{ts}.pdf"
                        pdf_path = os.path.join(user_dir, pdf_filename)
                        with open(pdf_path, 'wb') as f:
                            f.write(pdf_bytes)

                        # Get first page image and save
                        cover_image = get_pdf_first_page_image(pdf_path)
                        cover_path = None
                        if cover_image:
                            cover_filename = f"{safe_title}_{ts}.png"
                            cover_path = os.path.join(user_dir, cover_filename)
                            try:
                                cover_image.save(cover_path)
                            except Exception:
                                cover_path = None

                        book_obj = {
                            'title': title,
                            'author': author,
                            'pages': pages,
                            'current_page': 0,
                            'pages_read': 0,
                            'pdf_path': pdf_path,
                            'cover_path': cover_path,
                        }

                        # persist to user DB (avoid double-appending if lists reference same object)
                        users = st.session_state.users_db
                        user = users.get(st.session_state.current_user, {})
                        data = user.get('data', {})
                        data_books = data.get('books') if data.get('books') is not None else []

                        # ensure we don't already have this pdf_path
                        exists = any(b.get('pdf_path') == pdf_path for b in data_books)
                        if not exists:
                            data_books.append(book_obj)
                            data['books'] = data_books
                            user['data'] = data
                            users[st.session_state.current_user] = user
                            save_users(users)
                            st.session_state.users_db = users

                        # synchronize session books with saved user books (single source of truth)
                        st.session_state.books = data_books
                        st.success(f"✅ Added! ({pages}p)")
                        time.sleep(1)
                        st.rerun()
                    else:
                        st.error("❌ Could not read PDF. Invalid file?")
                except Exception as e:
                    st.error(f"❌ Upload failed: {str(e)}")
    
    st.divider()
    st.markdown("### 📖 Your Books")
    
    if st.session_state.books:
        cols = st.columns(3)
        for idx, book in enumerate(st.session_state.books):
            progress = (book.get('current_page', 0) / book['pages']) * 100
            
            with cols[idx % 3]:
                st.markdown(f"""
                    <div style='background: rgba(255, 107, 157, 0.15); border-radius: 15px; padding: 15px; border: 1px solid rgba(255, 107, 157, 0.25); text-align: center;'>
                """, unsafe_allow_html=True)
                
                # Display cover image if available
                cover_path = book.get('cover_path')
                if cover_path and isinstance(cover_path, str) and os.path.exists(cover_path):
                    st.image(cover_path, use_container_width=True)
                else:
                    st.markdown(f"<div style='background: linear-gradient(135deg, {COLORS['primary']} 0%, {COLORS['secondary']} 100%); height: 200px; border-radius: 10px; display: flex; align-items: center; justify-content: center;'><h3 style='color: white;'>📖</h3></div>", unsafe_allow_html=True)
                
                st.markdown(f"""
                    <h4 style='margin: 10px 0 5px 0;'>{book['title']}</h4>
                    <p style='margin: 0; color: rgba(255,255,255,0.6); font-size: 0.9em;'>{book['author']}</p>
                    <div style='margin: 10px 0;'><span class='badge'>{int(progress)}%</span></div>
                    <div style='color: rgba(255,255,255,0.7); font-size: 0.85em;'>{book.get("current_page", 0)}/{book["pages"]} pages</div>
                    </div>
                """, unsafe_allow_html=True)
                
                col1, col2, col3 = st.columns(3)
                with col1:
                    if st.button("📖", key=f"read_{idx}", help="Read"):
                        st.session_state.selected_book = idx
                with col2:
                    if st.button("👁️", key=f"view_{idx}", help="View PDF"):
                        st.session_state.view_pdf = idx
                with col3:
                    if st.button("🗑️", key=f"del_{idx}", help="Delete"):
                        # remove locally and delete files
                        # Use the stored user list as the source of truth to avoid double-removal
                        if st.session_state.current_user:
                            users = st.session_state.users_db
                            user = users.get(st.session_state.current_user, {})
                            data = user.get('data', {})
                            data_books = data.get('books', [])
                            if idx < len(data_books):
                                book_to_remove = data_books.pop(idx)
                                # delete files on disk if present
                                try:
                                    p = book_to_remove.get('pdf_path')
                                    if p and os.path.exists(p):
                                        os.remove(p)
                                except Exception:
                                    pass
                                try:
                                    c = book_to_remove.get('cover_path')
                                    if c and os.path.exists(c):
                                        os.remove(c)
                                except Exception:
                                    pass
                            data['books'] = data_books
                            user['data'] = data
                            users[st.session_state.current_user] = user
                            save_users(users)
                            st.session_state.users_db = users
                            # sync session books
                            st.session_state.books = data_books
                        else:
                            # not logged in: just pop local list
                            if idx < len(st.session_state.books):
                                book_to_remove = st.session_state.books.pop(idx)
                                try:
                                    p = book_to_remove.get('pdf_path')
                                    if p and os.path.exists(p):
                                        os.remove(p)
                                except Exception:
                                    pass
                                try:
                                    c = book_to_remove.get('cover_path')
                                    if c and os.path.exists(c):
                                        os.remove(c)
                                except Exception:
                                    pass
                        st.rerun()
    else:
        st.info("No books yet! Upload one to get started!")

# ==================== STATS ====================
elif page == "📊 Stats":
    st.markdown(f"<div class='header'>📊 Statistics</div>", unsafe_allow_html=True)
    st.divider()
    
    col1, col2, col3, col4 = st.columns(4)
    with col1:
        st.markdown(f"<div class='card'><div class='label'>Total Pages</div><div class='metric'>{st.session_state.stats['total_pages']}</div></div>", unsafe_allow_html=True)
    with col2:
        st.markdown(f"<div class='card'><div class='label'>Total Time</div><div class='metric'>{st.session_state.stats['total_time']}</div><div class='label'>mins</div></div>", unsafe_allow_html=True)
    with col3:
        avg = st.session_state.stats['total_pages'] / max(st.session_state.stats['total_time'], 1)
        st.markdown(f"<div class='card'><div class='label'>Speed</div><div class='metric'>{avg:.2f}</div><div class='label'>p/min</div></div>", unsafe_allow_html=True)
    with col4:
        st.markdown(f"<div class='card'><div class='label'>Points</div><div class='metric'>{st.session_state.stats['points']}</div></div>", unsafe_allow_html=True)
    
    st.divider()
    
    if st.session_state.books:
        col1, col2 = st.columns(2)
        with col1:
            st.markdown("### 📊 Book Progress")
            data = []
            for b in st.session_state.books:
                data.append({'Book': b['title'][:15], 'Read': b.get('pages_read', 0), 'Total': b['pages']})
            df = pd.DataFrame(data)
            fig = px.bar(df, x='Book', y=['Read', 'Total'], barmode='stack',
                        color_discrete_sequence=[COLORS['primary'], COLORS['accent']])
            fig.update_layout(template='plotly_dark', height=400, margin=dict(l=0,r=0,t=0,b=0))
            st.plotly_chart(fig, use_container_width=True)
        
        with col2:
            st.markdown("### 🎯 Goals")
            # Load user goals for Stats page
            stats_daily_goal = 30
            stats_weekly_goal = 200
            stats_monthly_goal = 800
            if st.session_state.current_user:
                try:
                    user_rec = st.session_state.users_db.get(st.session_state.current_user, {})
                    user_goals = user_rec.get('data', {}).get('goals', {})
                    stats_daily_goal = user_goals.get('daily', 30)
                    stats_weekly_goal = user_goals.get('weekly', 200)
                    stats_monthly_goal = user_goals.get('monthly', 800)
                except Exception:
                    pass
            
            goals = {
                'Goal': ['Daily', 'Weekly', 'Monthly'],
                'Progress': [
                    st.session_state.stats['total_pages'] % stats_daily_goal,
                    st.session_state.stats['weekly_pages'],
                    st.session_state.stats['monthly_pages']
                ],
                'Target': [stats_daily_goal, stats_weekly_goal, stats_monthly_goal]
            }
            df = pd.DataFrame(goals)
            fig = px.bar(df, x='Goal', y=['Progress', 'Target'], barmode='group',
                        color_discrete_sequence=[COLORS['secondary'], COLORS['warning']])
            fig.update_layout(template='plotly_dark', height=400, margin=dict(l=0,r=0,t=0,b=0))
            st.plotly_chart(fig, use_container_width=True)

# ==================== REWARDS ====================
elif page == "🎁 Rewards":
    st.markdown(f"<div class='header'>🎁 Rewards</div>", unsafe_allow_html=True)
    st.divider()
    
    # Load user goals for Rewards page
    rewards_weekly_goal = 200
    rewards_monthly_goal = 800
    if st.session_state.current_user:
        try:
            user_rec = st.session_state.users_db.get(st.session_state.current_user, {})
            goals = user_rec.get('data', {}).get('goals', {})
            rewards_weekly_goal = goals.get('weekly', 200)
            rewards_monthly_goal = goals.get('monthly', 800)
        except Exception:
            pass
    
    col1, col2, col3 = st.columns(3)
    with col1:
        st.markdown(f"<div class='card'><div class='label'>Points</div><div class='metric'>{st.session_state.stats['points']}</div></div>", unsafe_allow_html=True)
    with col2:
        weekly = st.session_state.stats['weekly_pages'] >= rewards_weekly_goal
        st.markdown(f"<div class='card'><div class='label'>Weekly Goal</div><div class='metric' style='color: {COLORS['success'] if weekly else COLORS['warning']};'>{'✅' if weekly else '⏳'}</div></div>", unsafe_allow_html=True)
    with col3:
        monthly = st.session_state.stats['monthly_pages'] >= rewards_monthly_goal
        st.markdown(f"<div class='card'><div class='label'>Monthly Goal</div><div class='metric' style='color: {COLORS['success'] if monthly else COLORS['warning']};'>{'✅' if monthly else '⏳'}</div></div>", unsafe_allow_html=True)
    
    st.divider()
    
    st.markdown("### 🎖️ Gift Card Eligibility")
    
    weekly = st.session_state.stats['weekly_pages'] >= rewards_weekly_goal
    monthly = st.session_state.stats['monthly_pages'] >= rewards_monthly_goal
    
    st.markdown(f"""
        <div class='card'>
            <div style='display: flex; align-items: center; gap: 10px; margin: 10px 0;'>
                <span style='font-size: 1.5em;'>{'✅' if weekly else '❌'}</span>
                <span>Weekly Goal: {st.session_state.stats['weekly_pages']}/{rewards_weekly_goal} pages</span>
            </div>
            <div style='display: flex; align-items: center; gap: 10px; margin: 10px 0;'>
                <span style='font-size: 1.5em;'>{'✅' if monthly else '❌'}</span>
                <span>Monthly Goal: {st.session_state.stats['monthly_pages']}/{rewards_monthly_goal} pages</span>
            </div>
        </div>
    """, unsafe_allow_html=True)
    
    if weekly and monthly:
        st.success("🎉 You're eligible for a $5 Gift Card!")
    else:
        w = max(0, rewards_weekly_goal - st.session_state.stats['weekly_pages'])
        m = max(0, rewards_monthly_goal - st.session_state.stats['monthly_pages'])
        st.info(f"📚 {w} pages for weekly • {m} pages for monthly")
    
    st.divider()
    
    st.markdown("### 🏆 Tiers")
    tiers = [
        {"name": "Bronze", "range": "0-200", "reward": "Avatar Pack"},
        {"name": "Silver", "range": "201-500", "reward": "Theme + Avatar"},
        {"name": "Gold", "range": "501-1000", "reward": "$2.50 Card"},
        {"name": "Platinum", "range": "1000+", "reward": "$5 Card"},
    ]
    
    for tier in tiers:
        st.markdown(f"""
            <div class='card'>
                <div style='display: flex; justify-content: space-between; align-items: center;'>
                    <div><h4 style='margin: 0;'>{tier['name']}</h4><p style='margin: 0; font-size: 0.9em;'>{tier['range']} pts</p></div>
                    <span class='badge'>{tier['reward']}</span>
                </div>
            </div>
        """, unsafe_allow_html=True)

# ==================== SETTINGS ====================
elif page == "⚙️ Settings":
    st.markdown(f"<div class='header'>⚙️ Settings</div>", unsafe_allow_html=True)
    st.divider()
    
    st.markdown("### 📖 Reading Goals")
    
    # Load current goals from user data
    daily_goal = 30
    weekly_goal = 200
    monthly_goal = 800
    if st.session_state.current_user:
        try:
            user_rec = st.session_state.users_db.get(st.session_state.current_user, {})
            goals = user_rec.get('data', {}).get('goals', {})
            daily_goal = goals.get('daily', 30)
            weekly_goal = goals.get('weekly', 200)
            monthly_goal = goals.get('monthly', 800)
        except Exception:
            pass
    
    col1, col2, col3 = st.columns(3)
    with col1:
        daily_goal_input = st.number_input("Daily Goal (pages)", min_value=1, max_value=500, value=int(daily_goal), key="daily_goal_input")
    with col2:
        weekly_goal_input = st.number_input("Weekly Goal (pages)", min_value=1, max_value=2000, value=int(weekly_goal), key="weekly_goal_input")
    with col3:
        monthly_goal_input = st.number_input("Monthly Goal (pages)", min_value=1, max_value=10000, value=int(monthly_goal), key="monthly_goal_input")
    
    st.divider()

    st.markdown("### 👤 Profile")
    col1, col2 = st.columns(2)
    with col1:
        name = st.text_input("Name", "Reader", key="name_input")
        email_display = st.session_state.current_user if st.session_state.current_user else "reader@example.com"
        email = st.text_input("Email", email_display, key="email_input", disabled=True)
    with col2:
        country = st.text_input("Country", "USA", key="country_input")
        theme = st.selectbox("Theme", ["Dark (Gen Z)", "Light"], key="theme_select")

    st.divider()

    # Per-user reading speed (WPM)
    user_wpm = None
    if st.session_state.current_user:
        try:
            user_rec = st.session_state.users_db.get(st.session_state.current_user, {})
            user_wpm = user_rec.get('data', {}).get('wpm')
        except Exception:
            user_wpm = None

    wpm = st.number_input("Reading speed (WPM)", min_value=50, max_value=1000, value=int(user_wpm) if user_wpm else 200)

    if st.button("💾 Save", use_container_width=True):
        # persist settings to user data if logged in
        if st.session_state.current_user:
            try:
                users = st.session_state.users_db
                user = users.get(st.session_state.current_user, {})
                data = user.get('data', {})
                data['wpm'] = int(wpm)
                data['goals'] = {
                    'daily': int(daily_goal_input),
                    'weekly': int(weekly_goal_input),
                    'monthly': int(monthly_goal_input),
                }
                data['name'] = name
                data['country'] = country
                user['data'] = data
                users[st.session_state.current_user] = user
                save_users(users)
                st.session_state.users_db = users
                st.success("✅ Settings saved!")
            except Exception as e:
                st.error(f"Failed to save: {e}")
        else:
            st.info("Log in to save profile settings.")
