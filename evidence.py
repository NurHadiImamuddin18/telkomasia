from flask import Flask, render_template, request, jsonify, send_file
from flask_cors import CORS
from io import BytesIO
from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas
from reportlab.lib.utils import ImageReader
from reportlab.platypus import SimpleDocTemplate, Paragraph, Table, TableStyle, Spacer, Image
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
CORS(app, resources={
    r"/api/*": {
        "origins": [
            "https://telkomasia-production.up.railway.app",  # ← Production domain
            "http://localhost:5000",  # ← Local testing
            "https://wzaojy07.up.railway.app",
            "http://127.0.0.1:5000"   # ← Local testing alternatif
        ],
        "methods": ["GET", "POST", "PUT", "DELETE"],
        "allow_headers": ["Content-Type", "X-User-Role"]
    }
})

load_dotenv()

# MySQL Configuration with MYSQL_URL support
MYSQL_URL = os.getenv("MYSQL_URL")

if MYSQL_URL:
    print("📌 Using MYSQL_URL for connection")
    try:
        url = urlparse(MYSQL_URL)
        DB_CONFIG = {
            'host': url.hostname,
            'database': url.path[1:] if url.path else '',
            'user': url.username,
            'password': url.password,
            'port': url.port or 3306
        }
    except Exception as e:
        print(f"❌ Error parsing MYSQL_URL: {e}")
        print("Falling back to individual variables")
        DB_CONFIG = {
            'host': os.getenv("MYSQLHOST"),
            'database': os.getenv("MYSQLDATABASE"),
            'user': os.getenv("MYSQLUSER"),
            'password': os.getenv("MYSQLPASSWORD"),
            'port': int(os.getenv("MYSQLPORT", 3306))
        }
else:
    print("📌 Using individual MySQL variables")
    DB_CONFIG = {
        'host': os.getenv("MYSQLHOST"),
        'database': os.getenv("MYSQLDATABASE"),
        'user': os.getenv("MYSQLUSER"),
        'password': os.getenv("MYSQLPASSWORD"),
        'port': int(os.getenv("MYSQLPORT", 3306))
    }

def admin_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        user_role = None
        user_role = request.headers.get('X-User-Role')
        
        if not user_role and request.is_json:
            data = request.json
            user_role = data.get('userRole') or data.get('role')
        
        if not user_role:
            user_role = request.form.get('userRole') or request.form.get('role')
        
        if user_role != 'admin':
            return jsonify({
                'success': False, 
                'message': 'Unauthorized. Admin access required.',
                'debug_info': f'Received role: {user_role}'
            }), 403
        
        return f(*args, **kwargs)
    return decorated_function

def get_db():
    """Connect to MySQL database with retry logic"""
    max_retries = 5
    retry_delay = 2
    
    for attempt in range(max_retries):
        try:
            print(f"🔄 Attempting database connection (attempt {attempt + 1}/{max_retries})...")
            print(f"   Host: {DB_CONFIG.get('host')}")
            print(f"   Port: {DB_CONFIG.get('port')}")
            print(f"   Database: {DB_CONFIG.get('database')}")
            print(f"   User: {DB_CONFIG.get('user')}")
            
            conn = mysql.connector.connect(**DB_CONFIG)
            print("✅ Connected to database successfully!")
            return conn
        except Error as e:
            print(f"❌ Connection attempt {attempt + 1} failed")
            print(f"   Error code: {e.errno if hasattr(e, 'errno') else 'N/A'}")
            print(f"   Error message: {e.msg if hasattr(e, 'msg') else str(e)}")
            
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
    """Initialize database with required tables"""
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
        
        # Table for users
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
        
        # Table for orders
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
        
        # Table for photos (DW photos)
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
        
        # Table for FAT photos
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
        
        # Insert default admin user if not exists
        cursor.execute('SELECT * FROM users WHERE username = %s', ('admin',))
        if not cursor.fetchone():
            cursor.execute('''
                INSERT INTO users (username, password, role) 
                VALUES (%s, %s, %s)
            ''', ('admin', 'admin123', 'admin'))
            print("   ✅ Admin user created: admin / admin123")
        else:
            print("   ℹ️  Admin user already exists")
        
        # Insert default user if not exists
        cursor.execute('SELECT * FROM users WHERE username = %s', ('teknisi',))
        if not cursor.fetchone():
            cursor.execute('''
                INSERT INTO users (username, password, role) 
                VALUES (%s, %s, %s)
            ''', ('teknisi', 'teknisi123', 'user'))
            print("   ✅ Teknisi user created: teknisi / teknisi123")
        else:
            print("   ℹ️  Teknisi user already exists")
        
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
        if cursor:
            cursor.close()
        if conn and conn.is_connected():
            conn.close()
            print("🔌 Database connection closed")

@app.route('/')
def index():
    """Serve the main HTML page"""
    return render_template('prototype_change_dw_fat_v2.1.html')

@app.route('/health')
def health():
    """Health check endpoint"""
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

@app.route('/api/login', methods=['POST'])
def login():
    """Handle user login"""
    data = request.json
    username = data.get('username')
    password = data.get('password')
    
    conn = get_db()
    if not conn:
        return jsonify({'success': False, 'message': 'Database connection failed'}), 500
    
    cursor = conn.cursor(dictionary=True)
    cursor.execute('SELECT * FROM users WHERE username = %s AND password = %s', 
                   (username, password))
    user = cursor.fetchone()
    cursor.close()
    conn.close()
    
    if user:
        return jsonify({
            'success': True,
            'user': {
                'username': user['username'],
                'role': user['role']
            }
        })
    else:
        return jsonify({'success': False, 'message': 'Invalid credentials'}), 401

@app.route('/api/users', methods=['GET'])
def get_users():
    """Get all users"""
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
@admin_required
def add_user():
    """Add new user"""
    data = request.json
    username = data.get('username')
    password = data.get('password')
    role = data.get('role', 'user')
    
    if not username or not password:
        return jsonify({'success': False, 'message': 'Username and password are required'}), 400
    
    conn = get_db()
    if not conn:
        return jsonify({'success': False, 'message': 'Database connection failed'}), 500
    
    cursor = conn.cursor()
    
    try:
        cursor.execute('''
            INSERT INTO users (username, password, role) 
            VALUES (%s, %s, %s)
        ''', (username, password, role))
        conn.commit()
        cursor.close()
        conn.close()
        return jsonify({'success': True, 'message': 'User added successfully'})
    except mysql.connector.IntegrityError:
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
@admin_required
def delete_user(user_id):
    """Delete user"""
    conn = get_db()
    if not conn:
        return jsonify({'success': False, 'message': 'Database connection failed'}), 500
    
    cursor = conn.cursor(dictionary=True)
    
    cursor.execute('SELECT role FROM users WHERE id = %s', (user_id,))
    user = cursor.fetchone()
    
    if user and user['role'] == 'admin':
        cursor.close()
        conn.close()
        return jsonify({'success': False, 'message': 'Cannot delete admin user'}), 400
    
    cursor.execute('DELETE FROM users WHERE id = %s', (user_id,))
    conn.commit()
    cursor.close()
    conn.close()
    
    return jsonify({'success': True, 'message': 'User deleted successfully'})

@app.route('/api/orders', methods=['POST'])
@admin_required
def create_order():
    """Create new order (DW or FAT)"""
    data = request.json
    order_id = data.get('orderId')
    order_type = data.get('type')
    nama_teknisi = data.get('namaTeknisi')
    materials = json.dumps(data.get('materials', []))
    foto_count = data.get('fotoCount', 0)
    created_by = data.get('createdBy')
    
    if not order_id or not order_type or not nama_teknisi:
        return jsonify({'success': False, 'message': 'Missing required fields'}), 400
    
    conn = get_db()
    if not conn:
        return jsonify({'success': False, 'message': 'Database connection failed'}), 500
    
    cursor = conn.cursor()
    
    try:
        cursor.execute('''
            INSERT INTO orders (order_id, type, nama_teknisi, materials, foto_count, created_by)
            VALUES (%s, %s, %s, %s, %s, %s)
        ''', (order_id, order_type, nama_teknisi, materials, foto_count, created_by))
        
        new_order_id = cursor.lastrowid
        
        if order_type == 'DW' and 'fotoData' in data:
            for idx, foto in enumerate(data['fotoData']):
                cursor.execute('''
                    INSERT INTO photos (order_id, image_data, caption, photo_index)
                    VALUES (%s, %s, %s, %s)
                ''', (new_order_id, foto['src'], foto.get('caption', ''), idx))
        
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
    """Get all orders"""
    conn = get_db()
    if not conn:
        return jsonify({'success': False, 'message': 'Database connection failed'}), 500
    
    cursor = conn.cursor(dictionary=True)
    cursor.execute('SELECT * FROM orders ORDER BY created_at DESC')
    orders = cursor.fetchall()
    
    result = []
    for order in orders:
        order_dict = dict(order)
        order_dict['materials'] = json.loads(order_dict['materials'])
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
    """Get order detail"""
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
    
    order_dict = dict(order)
    order_dict['materials'] = json.loads(order_dict['materials'])
    order_dict['orderId'] = order_dict['order_id']
    order_dict['namaTeknisi'] = order_dict['nama_teknisi']
    order_dict['fotoCount'] = order_dict['foto_count']
    order_dict['createdBy'] = order_dict.get('created_by')
    order_dict['createdAt'] = order_dict.get('created_at')
    
    if order_dict['type'] == 'DW':
        cursor.execute('SELECT image_data, caption, photo_index FROM photos WHERE order_id = %s ORDER BY photo_index', 
                      (order_id,))
        photos = cursor.fetchall()
        order_dict['fotoData'] = [{'src': p['image_data'], 'caption': p['caption']} for p in photos]
    
    if order_dict['type'] == 'FAT':
        cursor.execute('SELECT photo_key, image_data FROM fat_photos WHERE order_id = %s', 
                      (order_id,))
        fat_photos = cursor.fetchall()
        order_dict['fatPhotos'] = {p['photo_key']: p['image_data'] for p in fat_photos}
    
    cursor.close()
    conn.close()
    
    return jsonify({'success': True, 'order': order_dict})

@app.route('/api/orders/<int:order_id>', methods=['PUT'])
@admin_required
def update_order(order_id):
    """Update order"""
    data = request.json
    materials = json.dumps(data.get('materials', []))
    foto_count = data.get('fotoCount')
    
    conn = get_db()
    if not conn:
        return jsonify({'success': False, 'message': 'Database connection failed'}), 500
    
    cursor = conn.cursor()
    
    try:
        cursor.execute('''
            UPDATE orders 
            SET materials = %s, foto_count = %s
            WHERE id = %s
        ''', (materials, foto_count, order_id))
        
        if 'fotoData' in data:
            cursor.execute('DELETE FROM photos WHERE order_id = %s', (order_id,))
            for idx, foto in enumerate(data['fotoData']):
                cursor.execute('''
                    INSERT INTO photos (order_id, image_data, caption, photo_index)
                    VALUES (%s, %s, %s, %s)
                ''', (order_id, foto['src'], foto.get('caption', ''), idx))
        
        if 'fatPhotos' in data:
            cursor.execute('DELETE FROM fat_photos WHERE order_id = %s', (order_id,))
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
@admin_required
def delete_order(order_id):
    """Delete order"""
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

@app.route('/api/download-pdf/<int:order_id>', methods=['GET'])
def download_pdf(order_id):
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

    order_obj = {
        "orderId": order["order_id"],
        "namaTeknisi": order["nama_teknisi"],
        "type": order["type"],
        "fotoCount": order["foto_count"],
        "materials": json.loads(order["materials"]) if order["materials"] else [],
        "evidenceFiles": []
    }

    # Ambil foto evidence
    if order["type"] == "DW":
        cursor.execute("SELECT caption AS original_name, image_data FROM photos WHERE order_id=%s ORDER BY photo_index", (order_id,))
    else:
        cursor.execute("SELECT photo_key AS original_name, image_data FROM fat_photos WHERE order_id=%s", (order_id,))
    evidence_files = cursor.fetchall()
    cursor.close()
    conn.close()

    for f in evidence_files:
        order_obj["evidenceFiles"].append({
            "original_name": f.get("original_name", ""),
            "image_data": f.get("image_data")
        })

    # --- Generate PDF ---
    buffer = BytesIO()
    doc = SimpleDocTemplate(
        buffer,
        pagesize=A4,
        rightMargin=2*cm,
        leftMargin=2*cm,
        topMargin=2*cm,
        bottomMargin=2*cm
    )

    styles = getSampleStyleSheet()
    title_style = ParagraphStyle(
        'CustomTitle',
        parent=styles['Heading1'],
        fontSize=18,
        textColor=colors.HexColor('#1a3d7c'),
        alignment=TA_CENTER,
        spaceAfter=30
    )

    heading_style = ParagraphStyle(
        'CustomHeading',
        parent=styles['Heading2'],
        fontSize=14,
        textColor=colors.HexColor('#1a3d7c'),
        spaceBefore=20,
        spaceAfter=10
    )

    story = []

    # Title
    title = Paragraph(f"LAPORAN {order_obj['type']} - {order_obj['orderId']}", title_style)
    story.append(title)

    # Basic info
    story.append(Paragraph("INFORMASI DASAR", heading_style))
    basic_data = [
        ['Order ID', order_obj['orderId']],
        ['Nama Teknisi', order_obj['namaTeknisi']],
        ['Tipe Pekerjaan', order_obj['type']],
        ['Jumlah Foto Evidence', str(order_obj['fotoCount'])]
    ]
    basic_table = Table(basic_data, colWidths=[4*cm, 10*cm])
    basic_table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (0, -1), colors.HexColor('#f5f7fa')),
        ('GRID', (0, 0), (-1, -1), 1, colors.black),
        ('FONTNAME', (0, 0), (0, -1), 'Helvetica-Bold'),
        ('FONTNAME', (1, 0), (1, -1), 'Helvetica'),
        ('FONTSIZE', (0, 0), (-1, -1), 10),
        ('ALIGN', (0, 0), (-1, -1), 'LEFT'),
        ('VALIGN', (0, 0), (-1, -1), 'TOP')
    ]))
    story.append(basic_table)
    story.append(Spacer(1, 20))

    # Materials
    if order_obj['materials']:
        story.append(Paragraph("MATERIAL YANG DIGUNAKAN", heading_style))
        materials_data = [['No.', 'Material']]
        for i, material in enumerate(order_obj['materials'], 1):
            materials_data.append([str(i), material])

        materials_table = Table(materials_data, colWidths=[1.5*cm, 12.5*cm])
        materials_table.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#1a3d7c')),
            ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
            ('GRID', (0, 0), (-1, -1), 1, colors.black),
            ('ALIGN', (0, 0), (0, -1), 'CENTER'),
            ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
            ('FONTSIZE', (0, 0), (-1, -1), 10),
        ]))
        story.append(materials_table)
        story.append(Spacer(1, 20))

    # Evidence section
    if order_obj['evidenceFiles']:
    story.append(Paragraph("FOTO EVIDENCE", heading_style))

    # Header tabel
    evidence_data = [['No.', 'Foto Evidence', 'Keterangan Foto']]

        for idx, file_info in enumerate(order_obj['evidenceFiles'], 1):
            img_b64 = file_info.get("image_data")
            caption = file_info.get("original_name", "-")  # caption foto (bisa diubah sesuai kolom DB)
            foto_elemen = []
    
            # Tambahkan gambar
            if img_b64:
                try:
                    if "," in img_b64:
                        img_b64 = img_b64.split(",")[1]
                    img_bytes = base64.b64decode(img_b64)
                    img_reader = ImageReader(BytesIO(img_bytes))
                    img = Image(img_reader, width=6.5*cm, height=4.5*cm)  # ukuran pas 1 kolom
                    img.hAlign = 'CENTER'
                    foto_elemen.append(img)
                except Exception as e:
                    print(f"Gagal load gambar: {e}")
                    foto_elemen.append(Paragraph("(Gagal menampilkan gambar)", styles["Normal"]))
            else:
                foto_elemen.append(Paragraph("(Tidak ada gambar)", styles["Normal"]))
    
            # Tambahkan baris ke tabel
            evidence_data.append([
                str(idx),
                foto_elemen,
                Paragraph(caption, styles["Normal"])
            ])

            # Buat tabel 3 kolom
            evidence_table = Table(evidence_data, colWidths=[1.2*cm, 8*cm, 5*cm])
            evidence_table.setStyle(TableStyle([
                ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#1a3d7c')),
                ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
                ('GRID', (0, 0), (-1, -1), 1, colors.black),
                ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
                ('ALIGN', (0, 0), (0, -1), 'CENTER'),
                ('ALIGN', (1, 1), (1, -1), 'CENTER'),
                ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
                ('FONTSIZE', (0, 0), (-1, -1), 9),
                ('BOTTOMPADDING', (0, 0), (-1, -1), 6),
                ('TOPPADDING', (0, 0), (-1, -1), 6)
            ]))
            story.append(evidence_table)

    # Footer
    story.append(Spacer(1, 30))
    footer_text = f"Laporan dibuat otomatis pada {datetime.now().strftime('%d/%m/%Y %H:%M:%S')}"
    story.append(Paragraph(footer_text, styles['Normal']))

    doc.build(story)
    buffer.seek(0)
    filename = f"{order_obj['type']}_{order_obj['orderId']}.pdf"
    return send_file(buffer, as_attachment=True, download_name=filename, mimetype='application/pdf')
    
# Initialize database when module is loaded (works in production!)
print("\n" + "🚀" * 30)
print("STARTING FLASK APPLICATION")
print("🚀" * 30 + "\n")

init_db()

if __name__ == '__main__':
    if not os.path.exists('templates'):
        os.makedirs('templates')
    
    print("\n" + "=" * 60)
    print("🌐 Starting Development Server...")
    print("=" * 60)
    print("📍 Server running at: http://localhost:5000")
    print("=" * 60 + "\n")
    
    app.run(debug=True, host='0.0.0.0', port=5000)
