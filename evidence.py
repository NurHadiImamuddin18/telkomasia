from flask import Flask, render_template, request, jsonify, send_file
from flask_cors import CORS
from io import BytesIO
from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas
from reportlab.lib.utils import ImageReader
from reportlab.platypus import SimpleDocTemplate, Paragraph, Table, TableStyle, Spacer, Image, PageBreak
from reportlab.lib import colors
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.enums import TA_CENTER
from reportlab.lib.units import cm
from datetime import datetime
import mysql.connector
from mysql.connector import Error
import json
import base64
import os
import time
from functools import wraps
from dotenv import load_dotenv
from urllib.parse import urlparse

app = Flask(__name__)

# Konfigurasi CORS - mengizinkan akses dari domain tertentu
CORS(app, resources={
    r"/api/*": {  # Semua endpoint yang dimulai dengan /api/
        "origins": [
            "https://telkomasia-production.up.railway.app",  # Production domain
            "http://localhost:5000",  # Local development
            "https://wzaojy07.up.railway.app",
            "http://127.0.0.1:5000"  # Local development alternative
        ],
        "methods": ["GET", "POST", "PUT", "DELETE"],  # HTTP methods yang diizinkan
        "allow_headers": ["Content-Type", "X-User-Role"]  # Headers yang diizinkan
    }
})

# Load environment variables dari file .env
load_dotenv()

# ============================================
# DATABASE CONFIGURATION
# ============================================
# Ambil MYSQL_URL dari environment variable
MYSQL_URL = os.getenv("MYSQL_URL")

# Jika MYSQL_URL tersedia (format: mysql://user:pass@host:port/database)
if MYSQL_URL:
    print("📌 Using MYSQL_URL for connection")
    try:
        # Parse URL menjadi komponen-komponen database
        url = urlparse(MYSQL_URL)
        DB_CONFIG = {
            'host': url.hostname,  
            'database': url.path.lstrip('/'), 
            'user': url.username,  
            'password': url.password, 
            'port': url.port or 3306 
        }

# ============================================
# DECORATOR FUNCTIONS
# ============================================
def admin_required(f):
    """
    Decorator untuk memastikan hanya admin yang bisa akses endpoint tertentu
    Digunakan untuk endpoint: create, update, delete order dan user
    """
    @wraps(f)
    def decorated_function(*args, **kwargs):
        user_role = None
        
        # Cek role dari header HTTP
        user_role = request.headers.get('X-User-Role')
        
        # Jika tidak ada di header, cek dari body JSON
        if not user_role and request.is_json:
            data = request.json
            user_role = data.get('userRole') or data.get('role')
        
        # Jika tidak ada di JSON, cek dari form data
        if not user_role:
            user_role = request.form.get('userRole') or request.form.get('role')
        
        # Jika bukan admin, tolak akses
        if user_role != 'admin':
            return jsonify({
                'success': False, 
                'message': 'Unauthorized. Admin access required.',
                'debug_info': f'Received role: {user_role}'
            }), 403
        
        # Jika admin, lanjutkan ke fungsi yang di-wrap
        return f(*args, **kwargs)
    return decorated_function

# ============================================
# DATABASE FUNCTIONS
# ============================================
def get_db():
    """
    Koneksi ke MySQL database dengan retry logic
    Mencoba 5 kali dengan delay 2 detik antar percobaan
    """
    max_retries = 5  # Maksimal 5 kali percobaan
    retry_delay = 2  # Delay 2 detik antar percobaan
    
    for attempt in range(max_retries):
        try:
            print(f"🔄 Attempting database connection (attempt {attempt + 1}/{max_retries})...")
            print(f"   Host: {DB_CONFIG.get('host')}")
            print(f"   Port: {DB_CONFIG.get('port')}")
            print(f"   Database: {DB_CONFIG.get('database')}")
            print(f"   User: {DB_CONFIG.get('user')}")
            
            # Coba koneksi ke database
            conn = mysql.connector.connect(**DB_CONFIG)
            print("✅ Connected to database successfully!")
            return conn
            
        except Error as e:
            print(f"❌ Connection attempt {attempt + 1} failed")
            print(f"   Error code: {e.errno if hasattr(e, 'errno') else 'N/A'}")
            print(f"   Error message: {e.msg if hasattr(e, 'msg') else str(e)}")
            
            # Jika belum mencapai max retry, tunggu dan coba lagi
            if attempt < max_retries - 1:
                print(f"⏳ Retrying in {retry_delay} seconds...")
                time.sleep(retry_delay)
            else:
                print("❌ Max retries reached. Could not connect to database.")
                return None
                
        except Exception as e:
            print(f"❌ Unexpected error: {e}")
            return None
    
    return None

def init_db():
    """
    Initialize database dengan membuat tabel-tabel yang diperlukan
    dan insert default user (admin dan teknisi)
    Dipanggil saat aplikasi pertama kali dijalankan
    """
    print("=" * 60)
    print("🔧 INITIALIZING DATABASE")
    print("=" * 60)
    
    conn = get_db()
    if not conn:
        print("❌ Failed to connect to database. Skipping initialization.")
        print("⚠️  App will continue but database features won't work!")
        return False
    
    cursor = conn.cursor()
    
    try:
        print("📋 Creating tables...")
        
        # ===== TABEL USERS =====
        # Menyimpan data user (admin dan teknisi)
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS users (
                id INT AUTO_INCREMENT PRIMARY KEY,
                username VARCHAR(255) UNIQUE NOT NULL,
                password VARCHAR(255) NOT NULL,
                role VARCHAR(50) NOT NULL DEFAULT 'user',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        print("   ✅ Table 'users' created/verified")
        
        # ===== TABEL ORDERS =====
        # Menyimpan data order (DW atau FAT)
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS orders (
                id INT AUTO_INCREMENT PRIMARY KEY,
                order_id VARCHAR(255) NOT NULL,
                type VARCHAR(50) NOT NULL,
                nama_teknisi VARCHAR(255) NOT NULL,
                materials TEXT,
                foto_count INT DEFAULT 0,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                created_by VARCHAR(255)
            )
        ''')
        print("   ✅ Table 'orders' created/verified")
        
        # ===== TABEL PHOTOS =====
        # Menyimpan foto evidence untuk order DW
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS photos (
                id INT AUTO_INCREMENT PRIMARY KEY,
                order_id INT,
                image_data LONGTEXT,
                caption TEXT,
                photo_index INT,
                FOREIGN KEY (order_id) REFERENCES orders(id) ON DELETE CASCADE
            )
        ''')
        print("   ✅ Table 'photos' created/verified")
        
        # ===== TABEL FAT_PHOTOS =====
        # Menyimpan foto evidence untuk order FAT
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS fat_photos (
                id INT AUTO_INCREMENT PRIMARY KEY,
                order_id INT,
                photo_key VARCHAR(100) NOT NULL,
                image_data LONGTEXT NOT NULL,
                FOREIGN KEY (order_id) REFERENCES orders(id) ON DELETE CASCADE
            )
        ''')
        print("   ✅ Table 'fat_photos' created/verified")
        
        print("\n👤 Creating default users...")
        
        # Insert default admin user jika belum ada
        cursor.execute('SELECT * FROM users WHERE username = %s', ('admin',))
        if not cursor.fetchone():
            cursor.execute('''
                INSERT INTO users (username, password, role) 
                VALUES (%s, %s, %s)
            ''', ('admin', 'admin123', 'admin'))
            print("   ✅ Admin user created: admin / admin123")
        else:
            print("   ℹ️  Admin user already exists")
        
        # Insert default teknisi user jika belum ada
        cursor.execute('SELECT * FROM users WHERE username = %s', ('teknisi',))
        if not cursor.fetchone():
            cursor.execute('''
                INSERT INTO users (username, password, role) 
                VALUES (%s, %s, %s)
            ''', ('teknisi', 'teknisi123', 'user'))
            print("   ✅ Teknisi user created: teknisi / teknisi123")
        else:
            print("   ℹ️  Teknisi user already exists")
        
        # Commit semua perubahan ke database
        conn.commit()
        
        print("\n" + "=" * 60)
        print("✅ DATABASE INITIALIZATION SUCCESSFUL!")
        print("=" * 60)
        print("📌 Default credentials:")
        print("   👔 Admin: admin / admin123")
        print("   👷 User: teknisi / teknisi123")
        print("=" * 60)
        
        return True
        
    except Error as e:
        print(f"\n❌ Error initializing database:")
        print(f"   Error code: {e.errno if hasattr(e, 'errno') else 'N/A'}")
        print(f"   Error message: {e.msg if hasattr(e, 'msg') else str(e)}")
        return False
    except Exception as e:
        print(f"\n❌ Unexpected error: {e}")
        return False
    finally:
        # Tutup koneksi database
        if cursor:
            cursor.close()
        if conn and conn.is_connected():
            conn.close()
            print("🔌 Database connection closed")

# ============================================
# ROUTE: MAIN PAGE
# ============================================
@app.route('/')
def index():
    """Serve halaman HTML utama"""
    return render_template('prototype_change_dw_fat_v2.1.html')

# ============================================
# ROUTE: HEALTH CHECK
# ============================================
@app.route('/health')
def health():
    """Endpoint untuk cek status aplikasi dan database"""
    conn = get_db()
    if conn:
        conn.close()
        return jsonify({
            'status': 'healthy', 
            'database': 'connected',
            'config': {
                'host': DB_CONFIG.get('host'),
                'port': DB_CONFIG.get('port'),
                'database': DB_CONFIG.get('database')
            }
        }), 200
    return jsonify({
        'status': 'unhealthy', 
        'database': 'disconnected'
    }), 500

# ============================================
# ROUTE: LOGIN
# ============================================
@app.route('/api/login', methods=['POST'])
def login():
    """
    Handle user login
    Cek username dan password dari database
    Return user info jika valid
    """
    data = request.json
    username = data.get('username')
    password = data.get('password')
    
    conn = get_db()
    if not conn:
        return jsonify({'success': False, 'message': 'Database connection failed'}), 500
    
    cursor = conn.cursor(dictionary=True)
    # Query user berdasarkan username dan password
    cursor.execute('SELECT * FROM users WHERE username = %s AND password = %s', 
                   (username, password))
    user = cursor.fetchone()
    cursor.close()
    conn.close()
    
    if user:
        # Login berhasil, return user data
        return jsonify({
            'success': True,
            'user': {
                'username': user['username'],
                'role': user['role']
            }
        })
    else:
        # Login gagal
        return jsonify({'success': False, 'message': 'Invalid credentials'}), 401

# ============================================
# ROUTE: USER MANAGEMENT
# ============================================
@app.route('/api/users', methods=['GET'])
def get_users():
    """Get semua users dari database"""
    conn = get_db()
    if not conn:
        return jsonify({'success': False, 'message': 'Database connection failed'}), 500
    
    cursor = conn.cursor(dictionary=True)
    cursor.execute('SELECT id, username, role, created_at FROM users')
    users = cursor.fetchall()
    cursor.close()
    conn.close()
    
    return jsonify({'success': True, 'users': users})

@app.route('/api/users', methods=['POST'])
@admin_required  # Hanya admin yang bisa tambah user
def add_user():
    """
    Tambah user baru
    Hanya bisa dilakukan oleh admin
    """
    data = request.json
    username = data.get('username')
    password = data.get('password')
    role = data.get('role', 'user')
    
    # Validasi input
    if not username or not password:
        return jsonify({'success': False, 'message': 'Username and password are required'}), 400
    
    conn = get_db()
    if not conn:
        return jsonify({'success': False, 'message': 'Database connection failed'}), 500
    
    cursor = conn.cursor()
    
    try:
        # Insert user baru
        cursor.execute('''
            INSERT INTO users (username, password, role) 
            VALUES (%s, %s, %s)
        ''', (username, password, role))
        conn.commit()
        cursor.close()
        conn.close()
        return jsonify({'success': True, 'message': 'User added successfully'})
        
    except mysql.connector.IntegrityError:
        # Username sudah ada (karena UNIQUE constraint)
        conn.rollback()
        cursor.close()
        conn.close()
        return jsonify({'success': False, 'message': 'Username already exists'}), 400
        
    except Error as e:
        conn.rollback()
        cursor.close()
        conn.close()
        return jsonify({'success': False, 'message': str(e)}), 500

@app.route('/api/users/<int:user_id>', methods=['DELETE'])
@admin_required  # Hanya admin yang bisa delete user
def delete_user(user_id):
    """
    Delete user berdasarkan ID
    Admin user tidak bisa dihapus
    """
    conn = get_db()
    if not conn:
        return jsonify({'success': False, 'message': 'Database connection failed'}), 500
    
    cursor = conn.cursor(dictionary=True)
    
    # Cek apakah user adalah admin
    cursor.execute('SELECT role FROM users WHERE id = %s', (user_id,))
    user = cursor.fetchone()
    
    if user and user['role'] == 'admin':
        # Tidak boleh hapus admin
        cursor.close()
        conn.close()
        return jsonify({'success': False, 'message': 'Cannot delete admin user'}), 400
    
    # Delete user
    cursor.execute('DELETE FROM users WHERE id = %s', (user_id,))
    conn.commit()
    cursor.close()
    conn.close()
    
    return jsonify({'success': True, 'message': 'User deleted successfully'})

# ============================================
# ROUTE: ORDER MANAGEMENT
# ============================================
@app.route('/api/orders', methods=['POST'])
@admin_required  # Hanya admin yang bisa create order
def create_order():
    """
    Create order baru (DW atau FAT)
    Termasuk menyimpan foto evidence
    """
    data = request.json
    order_id = data.get('orderId')
    order_type = data.get('type')
    nama_teknisi = data.get('namaTeknisi')
    materials = json.dumps(data.get('materials', []))  # Convert array to JSON string
    foto_count = data.get('fotoCount', 0)
    created_by = data.get('createdBy')
    
    # Validasi input
    if not order_id or not order_type or not nama_teknisi:
        return jsonify({'success': False, 'message': 'Missing required fields'}), 400
    
    conn = get_db()
    if not conn:
        return jsonify({'success': False, 'message': 'Database connection failed'}), 500
    
    cursor = conn.cursor()
    
    try:
        # Insert order ke tabel orders
        cursor.execute('''
            INSERT INTO orders (order_id, type, nama_teknisi, materials, foto_count, created_by)
            VALUES (%s, %s, %s, %s, %s, %s)
        ''', (order_id, order_type, nama_teknisi, materials, foto_count, created_by))
        
        # Ambil ID order yang baru dibuat
        new_order_id = cursor.lastrowid
        
        # Jika tipe DW, simpan foto ke tabel photos
        if order_type == 'DW' and 'fotoData' in data:
            for idx, foto in enumerate(data['fotoData']):
                cursor.execute('''
                    INSERT INTO photos (order_id, image_data, caption, photo_index)
                    VALUES (%s, %s, %s, %s)
                ''', (new_order_id, foto['src'], foto.get('caption', ''), idx))
        
        # Jika tipe FAT, simpan foto ke tabel fat_photos
        if order_type == 'FAT' and 'fatPhotos' in data:
            for key, image_data in data['fatPhotos'].items():
                cursor.execute('''
                    INSERT INTO fat_photos (order_id, photo_key, image_data)
                    VALUES (%s, %s, %s)
                ''', (new_order_id, key, image_data))
        
        conn.commit()
        cursor.close()
        conn.close()
        
        return jsonify({'success': True, 'message': 'Order created successfully', 'id': new_order_id})
        
    except Error as e:
        conn.rollback()
        cursor.close()
        conn.close()
        return jsonify({'success': False, 'message': str(e)}), 500

@app.route('/api/orders', methods=['GET'])
def get_orders():
    """
    Get semua orders dari database
    Urutkan berdasarkan tanggal terbaru
    """
    conn = get_db()
    if not conn:
        return jsonify({'success': False, 'message': 'Database connection failed'}), 500
    
    cursor = conn.cursor(dictionary=True)
    cursor.execute('SELECT * FROM orders ORDER BY created_at DESC')
    orders = cursor.fetchall()
    
    # Format data untuk response
    result = []
    for order in orders:
        order_dict = dict(order)
        order_dict['materials'] = json.loads(order_dict['materials'])  # Parse JSON string ke array
        order_dict['orderId'] = order_dict['order_id']
        order_dict['namaTeknisi'] = order_dict['nama_teknisi']
        order_dict['fotoCount'] = order_dict['foto_count']
        order_dict['createdBy'] = order_dict.get('created_by')
        order_dict['createdAt'] = order_dict.get('created_at')
        result.append(order_dict)
    
    cursor.close()
    conn.close()
    
    return jsonify({'success': True, 'orders': result})

@app.route('/api/orders/<int:order_id>', methods=['GET'])
def get_order_detail(order_id):
    """
    Get detail order berdasarkan ID
    Termasuk foto evidence
    """
    conn = get_db()
    if not conn:
        return jsonify({'success': False, 'message': 'Database connection failed'}), 500
    
    cursor = conn.cursor(dictionary=True)
    cursor.execute('SELECT * FROM orders WHERE id = %s', (order_id,))
    order = cursor.fetchone()
    
    if not order:
        cursor.close()
        conn.close()
        return jsonify({'success': False, 'message': 'Order not found'}), 404
    
    # Format data order
    order_dict = dict(order)
    order_dict['materials'] = json.loads(order_dict['materials'])
    order_dict['orderId'] = order_dict['order_id']
    order_dict['namaTeknisi'] = order_dict['nama_teknisi']
    order_dict['fotoCount'] = order_dict['foto_count']
    order_dict['createdBy'] = order_dict.get('created_by')
    order_dict['createdAt'] = order_dict.get('created_at')
    
    # Jika tipe DW, ambil foto dari tabel photos
    if order_dict['type'] == 'DW':
        cursor.execute('SELECT image_data, caption, photo_index FROM photos WHERE order_id = %s ORDER BY photo_index', 
                      (order_id,))
        photos = cursor.fetchall()
        order_dict['fotoData'] = [{'src': p['image_data'], 'caption': p['caption']} for p in photos]
    
    # Jika tipe FAT, ambil foto dari tabel fat_photos
    if order_dict['type'] == 'FAT':
        cursor.execute('SELECT photo_key, image_data FROM fat_photos WHERE order_id = %s', 
                      (order_id,))
        fat_photos = cursor.fetchall()
        order_dict['fatPhotos'] = {p['photo_key']: p['image_data'] for p in fat_photos}
    
    cursor.close()
    conn.close()
    
    return jsonify({'success': True, 'order': order_dict})

@app.route('/api/orders/<int:order_id>', methods=['PUT'])
@admin_required  # Hanya admin yang bisa update order
def update_order(order_id):
    """
    Update order berdasarkan ID
    Termasuk update foto evidence
    """
    data = request.json
    materials = json.dumps(data.get('materials', []))
    foto_count = data.get('fotoCount')
    
    conn = get_db()
    if not conn:
        return jsonify({'success': False, 'message': 'Database connection failed'}), 500
    
    cursor = conn.cursor()
    
    try:
        # Update data order
        cursor.execute('''
            UPDATE orders 
            SET materials = %s, foto_count = %s
            WHERE id = %s
        ''', (materials, foto_count, order_id))
        
        # Update foto DW
        if 'fotoData' in data:
            # Hapus foto lama
            cursor.execute('DELETE FROM photos WHERE order_id = %s', (order_id,))
            # Insert foto baru
            for idx, foto in enumerate(data['fotoData']):
                cursor.execute('''
                    INSERT INTO photos (order_id, image_data, caption, photo_index)
                    VALUES (%s, %s, %s, %s)
                ''', (order_id, foto['src'], foto.get('caption', ''), idx))
        
        # Update foto FAT
        if 'fatPhotos' in data:
            # Hapus foto lama
            cursor.execute('DELETE FROM fat_photos WHERE order_id = %s', (order_id,))
            # Insert foto baru
            for key, image_data in data['fatPhotos'].items():
                cursor.execute('''
                    INSERT INTO fat_photos (order_id, photo_key, image_data)
                    VALUES (%s, %s, %s)
                ''', (order_id, key, image_data))
        
        conn.commit()
        cursor.close()
        conn.close()
        
        return jsonify({'success': True, 'message': 'Order updated successfully'})
        
    except Error as e:
        conn.rollback()
        cursor.close()
        conn.close()
        return jsonify({'success': False, 'message': str(e)}), 500

@app.route('/api/orders/<int:order_id>', methods=['DELETE'])
@admin_required  # Hanya admin yang bisa delete order
def delete_order(order_id):
    """
    Delete order berdasarkan ID
    Foto akan otomatis terhapus karena ON DELETE CASCADE
    """
    conn = get_db()
    if not conn:
        return jsonify({'success': False, 'message': 'Database connection failed'}), 500
    
    cursor = conn.cursor()
    
    try:
        cursor.execute('DELETE FROM orders WHERE id = %s', (order_id,))
        conn.commit()
        cursor.close()
        conn.close()
        
        return jsonify({'success': True, 'message': 'Order deleted successfully'})
        
    except Error as e:
        conn.rollback()
        cursor.close()
        conn.close()
        return jsonify({'success': False, 'message': str(e)}), 500

# ============================================
# ROUTE: TEST IMAGE (FOR DEBUGGING)
# ============================================
@app.route('/api/test-image/<int:photo_id>')
def test_image(photo_id):
    """
    Endpoint untuk test apakah foto bisa di-render
    Berguna untuk debugging
    """
    conn = get_db()
    cursor = conn.cursor(dictionary=True)
    cursor.execute('SELECT image_data FROM photos WHERE id = %s', (photo_id,))
    photo = cursor.fetchone()
    cursor.close()
    conn.close()
    
    if not photo:
        return "Photo not found", 404
    
    img_b64 = photo['image_data']
    
    # Bersihkan base64 string (hapus data:image prefix)
    if "," in img_b64:
        img_b64 = img_b64.split(",")[1]
    
    # Decode base64 menjadi bytes
    img_bytes = base64.b64decode(img_b64)
    
    # Return sebagai file image
    return send_file(
        BytesIO(img_bytes),
        mimetype='image/jpeg'
    )

# ============================================
# ROUTE: DOWNLOAD PDF
# ============================================
@app.route('/api/download-pdf/<int:order_id>', methods=['GET'])
def download_pdf(order_id):
    """
    Generate dan download PDF laporan berdasarkan order ID
    PDF berisi: Info order, material, dan foto evidence
    """
    # Ambil data order dari database
    conn = get_db()
    cursor = conn.cursor(dictionary=True)
    cursor.execute('SELECT * FROM orders WHERE id = %s', (order_id,))
    order = cursor.fetchone()
    
    if not order:
        return jsonify({'success': False, 'message': 'Order not found'}), 404

    # Format data order
    order_obj = {
        "orderId": order["order_id"],
        "namaTeknisi": order["nama_teknisi"],
        "type": order["type"],
        "fotoCount": order["foto_count"],
        "materials": json.loads(order["materials"]) if order["materials"] else []
    }

    # Ambil foto evidence berdasarkan tipe order
    if order["type"] == "DW":
        cursor.execute("SELECT caption AS caption, image_data FROM photos WHERE order_id=%s ORDER BY photo_index", (order_id,))
    else:  # FAT
        cursor.execute("SELECT photo_key AS caption, image_data FROM fat_photos WHERE order_id=%s", (order_id,))
    fotos = cursor.fetchall()
    cursor.close()
    conn.close()

    # ===================================
    # GENERATE PDF MENGGUNAKAN PLATYPUS
    # ===================================
    # Buat buffer untuk menyimpan PDF di memory
    buffer = BytesIO()
    
    # Setup dokumen PDF dengan ukuran A4 dan margin
    doc = SimpleDocTemplate(
        buffer,
        pagesize=A4,
        rightMargin=40,  # Margin kanan 40 points
        leftMargin=40,   # Margin kiri 40 points
        topMargin=50,    # Margin atas 50 points
        bottomMargin=50  # Margin bawah 50 points
    )
    
    # Container untuk menampung semua elemen PDF
    elements = []
    
    # Ambil style default dari ReportLab
    styles = getSampleStyleSheet()
    
    # ===================================
    # CUSTOM STYLES UNTUK PDF
    # ===================================
    # Style untuk judul utama
    title_style = ParagraphStyle(
        'CustomTitle',
        parent=styles['Heading1'],
        fontSize=18,
        textColor=colors.HexColor('#1a3d7c'),  # Warna biru tua
        spaceAfter=30,  # Jarak setelah judul
        alignment=TA_CENTER,  # Center alignment
        fontName='Helvetica-Bold'
    )
    
    # Style untuk heading section
    heading_style = ParagraphStyle(
        'CustomHeading',
        parent=styles['Heading2'],
        fontSize=14,
        textColor=colors.HexColor('#1a3d7c'),
        spaceAfter=12,  # Jarak setelah heading
        spaceBefore=20,  # Jarak sebelum heading
        fontName='Helvetica-Bold'
    )
    
    # Style untuk teks normal
    normal_style = ParagraphStyle(
        'CustomNormal',
        parent=styles['Normal'],
        fontSize=11,
        spaceAfter=6
    )

    # ===================================
    # BAGIAN 1: HEADER / JUDUL
    # ===================================
    title = Paragraph(f"LAPORAN {order_obj['type']} - {order_obj['orderId']}", title_style)
    elements.append(title)
    elements.append(Spacer(1, 10))  # Tambah spacing 10 points

    # ===================================
    # BAGIAN 2: INFORMASI DASAR
    # ===================================
    elements.append(Paragraph("INFORMASI DASAR", heading_style))
    
    # Data informasi dalam bentuk list 2D untuk tabel
    info_data = [
        ['Order ID', ':', order_obj['orderId']],
        ['Nama Teknisi', ':', order_obj['namaTeknisi']],
        ['Tipe Pekerjaan', ':', order_obj['type']],
        ['Jumlah Foto', ':', str(order_obj['fotoCount'])],
        ['Tanggal', ':', datetime.now().strftime('%d/%m/%Y %H:%M:%S')]
    ]
    
    # Buat tabel dengan 3 kolom (Label : Value)
    info_table = Table(info_data, colWidths=[3.5*cm, 0.5*cm, 12*cm])
    info_table.setStyle(TableStyle([
        ('FONTNAME', (0, 0), (-1, -1), 'Helvetica'),  # Font semua cell
        ('FONTSIZE', (0, 0), (-1, -1), 11),  # Ukuran font
        ('FONTNAME', (0, 0), (0, -1), 'Helvetica-Bold'),  # Bold untuk kolom pertama (label)
        ('TEXTCOLOR', (0, 0), (0, -1), colors.HexColor('#1a3d7c')),  # Warna biru untuk label
        ('VALIGN', (0, 0), (-1, -1), 'TOP'),  # Vertical alignment
        ('LEFTPADDING', (0, 0), (-1, -1), 0),  # Padding kiri
        ('RIGHTPADDING', (0, 0), (-1, -1), 0),  # Padding kanan
        ('BOTTOMPADDING', (0, 0), (-1, -1), 5),  # Padding bawah
    ]))
    
    elements.append(info_table)
    elements.append(Spacer(1, 15))  # Tambah spacing

    # ===================================
    # BAGIAN 3: MATERIAL
    # ===================================
    if order_obj['materials']:
        elements.append(Paragraph("MATERIAL YANG DIGUNAKAN", heading_style))
        
        # Data material dalam bentuk list 2D (Nomor + Nama Material)
        material_data = [[str(i), material] for i, material in enumerate(order_obj['materials'], 1)]
        
        # Buat tabel material dengan 2 kolom
        material_table = Table(material_data, colWidths=[1*cm, 15*cm])
        material_table.setStyle(TableStyle([
            ('FONTNAME', (0, 0), (-1, -1), 'Helvetica'),
            ('FONTSIZE', (0, 0), (-1, -1), 11),
            ('FONTNAME', (0, 0), (0, -1), 'Helvetica-Bold'),  # Bold untuk nomor
            ('VALIGN', (0, 0), (-1, -1), 'TOP'),
            ('LEFTPADDING', (0, 0), (-1, -1), 5),
            ('RIGHTPADDING', (0, 0), (-1, -1), 5),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 6),
            ('GRID', (0, 0), (-1, -1), 0.5, colors.grey),  # Grid border
            ('BACKGROUND', (0, 0), (-1, -1), colors.HexColor('#f8f9fa')),  # Background abu-abu muda
        ]))
        
        elements.append(material_table)
        elements.append(Spacer(1, 20))

    # ===================================
    # PAGE BREAK - PINDAH KE HALAMAN BARU
    # ===================================
    # Foto evidence akan dimulai di halaman baru
    elements.append(PageBreak())

    # ===================================
    # BAGIAN 4: FOTO EVIDENCE
    # ===================================
    elements.append(Paragraph("FOTO EVIDENCE", heading_style))
    elements.append(Spacer(1, 10))

    # Loop untuk setiap foto
    for idx, foto in enumerate(fotos, 1):
        img_b64 = foto.get("image_data")  # Data foto dalam base64
        caption = foto.get("caption", "-")  # Keterangan foto

        # Skip jika foto kosong
        if not img_b64:
            continue

        try:
            # ===================================
            # PROSES DECODE GAMBAR
            # ===================================
            # Bersihkan base64 string (hapus prefix data:image/...)
            if isinstance(img_b64, str) and "," in img_b64:
                img_b64 = img_b64.split(",")[1]
            
            # Decode base64 menjadi bytes
            img_bytes = base64.b64decode(img_b64)
            
            # Buat Image object dari ReportLab
            img = Image(BytesIO(img_bytes))
            
            # Set ukuran foto
            # Ukuran disesuaikan agar tidak terlalu besar
            img.drawWidth = 6.52*cm   # Lebar 6.52 cm
            img.drawHeight = 8.7*cm   # Tinggi 8.7 cm
            img.hAlign = 'CENTER'     # Foto di-center
            
            # ===================================
            # BUAT TABEL UNTUK FOTO
            # ===================================
            # Setiap foto dibungkus dalam tabel dengan 3 baris:
            # 1. Header (Foto X)
            # 2. Gambar
            # 3. Keterangan
            foto_data = [
                [Paragraph(f"<b>Foto {idx}</b>", normal_style)],  # Header
                [img],  # Gambar
                [Paragraph(f"<i>Keterangan: {caption}</i>", normal_style)]  # Keterangan
            ]
            
            # Buat tabel dengan 1 kolom
            foto_table = Table(foto_data, colWidths=[16*cm])
            foto_table.setStyle(TableStyle([
                ('ALIGN', (0, 0), (-1, -1), 'CENTER'),  # Semua content di-center
                ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),  # Vertical center
                ('TOPPADDING', (0, 0), (-1, -1), 10),
                ('BOTTOMPADDING', (0, 0), (-1, -1), 10),
                ('LEFTPADDING', (0, 0), (-1, -1), 10),
                ('RIGHTPADDING', (0, 0), (-1, -1), 10),
                ('BOX', (0, 0), (-1, -1), 1, colors.grey),  # Border box
                ('BACKGROUND', (0, 0), (0, 0), colors.HexColor('#e8f4f8')),  # Background header biru muda
                ('BACKGROUND', (0, 2), (0, 2), colors.HexColor('#f8f9fa')),  # Background keterangan abu-abu
            ]))
            
            elements.append(foto_table)
            elements.append(Spacer(1, 20))  # Spacing antar foto
            
        except Exception as e:
            # Jika gagal render foto, tampilkan pesan error
            print(f"⚠️ Gagal render foto {idx}: {e}")
            error_msg = Paragraph(f"<i>Foto {idx}: Gagal memuat gambar</i>", normal_style)
            elements.append(error_msg)
            elements.append(Spacer(1, 10))

    # ===================================
    # BAGIAN 5: FOOTER
    # ===================================
    footer_style = ParagraphStyle(
        'Footer',
        parent=styles['Normal'],
        fontSize=9,
        textColor=colors.grey,  # Warna abu-abu
        alignment=TA_CENTER
    )
    elements.append(Spacer(1, 30))
    footer_text = f"Dokumen dibuat otomatis pada {datetime.now().strftime('%d/%m/%Y %H:%M:%S')}"
    elements.append(Paragraph(footer_text, footer_style))

    # ===================================
    # BUILD PDF
    # ===================================
    # Gabungkan semua elemen dan generate PDF
    doc.build(elements)
    
    # Reset buffer position ke awal
    buffer.seek(0)
    
    # Buat nama file
    filename = f"{order_obj['type']}_{order_obj['orderId']}.pdf"
    
    # Return file PDF untuk di-download
    return send_file(buffer, as_attachment=True, download_name=filename, mimetype='application/pdf')

# ============================================
# APPLICATION STARTUP
# ============================================
# Print banner saat aplikasi dimulai
print("\n" + "🚀" * 30)
print("STARTING FLASK APPLICATION")
print("🚀" * 30 + "\n")

# Initialize database (create tables dan default users)
init_db()

# ============================================
# RUN SERVER
# ============================================
if __name__ == '__main__':
    # Buat folder templates jika belum ada
    if not os.path.exists('templates'):
        os.makedirs('templates')
    
    print("\n" + "=" * 60)
    print("🌐 Starting Development Server...")
    print("=" * 60)
    print("📍 Server running at: http://localhost:5000")
    print("=" * 60 + "\n")
    
    # Jalankan Flask development server
    # debug=True: Auto-reload saat code berubah
    # host='0.0.0.0': Bisa diakses dari jaringan
    # port=5000: Port yang digunakan
    app.run(debug=True, host='0.0.0.0', port=5000)

