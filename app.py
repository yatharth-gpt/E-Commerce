import os
from flask import Flask, render_template, request, redirect, url_for, session, flash, jsonify, send_file, Response
from database import init_db, get_db, seed_products
from functools import wraps
from pathlib import Path
from datetime import datetime, timedelta
from werkzeug.utils import secure_filename
from reportlab.pdfgen import canvas
from reportlab.lib.pagesizes import A4
from io import BytesIO, StringIO
from csv import writer
from urllib.parse import quote
import qrcode, re, json

app=Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "change-this-secret-key")
UPLOAD_FOLDER=Path(app.root_path)/"static"/"uploads"
UPLOAD_FOLDER.mkdir(parents=True,exist_ok=True)
init_db(); seed_products()

def admin_required(view):
    @wraps(view)
    def wrapped(*args,**kwargs):
        if not session.get("admin_logged_in"): return redirect(url_for("admin_login"))
        return view(*args,**kwargs)
    return wrapped

def settings_dict():
    db=get_db()
    return {r["key"]:r["value"] for r in db.execute("SELECT key,value FROM settings").fetchall()}

def create_notification(db,order_id,channel,message):
    db.execute("INSERT INTO notifications(order_id,channel,message,status) VALUES(?,?,?,'Pending')",(order_id,channel,message))

def queue_external_notifications(db, order_id, message, phone=''):
    # Real SMS/WhatsApp APIs can be connected later. The queue is stored now so no event is lost.
    create_notification(db, order_id, 'SMS', message)
    create_notification(db, order_id, 'WhatsApp', message)

def apply_auto_price(db, product_id, new_purchase, reason='Purchase price changed'):
    p=db.execute('SELECT * FROM products WHERE id=?',(product_id,)).fetchone()
    if not p: return None
    rule=db.execute('SELECT * FROM price_rules WHERE product_id=?',(product_id,)).fetchone()
    margin=float(rule['margin_percent'] if rule else settings_dict().get('default_margin_percent','12'))
    old_purchase=float(p['purchase_price']); old_price=float(p['price'])
    new_price=round(float(new_purchase)*(1+margin/100),2)
    db.execute('UPDATE products SET purchase_price=?,price=? WHERE id=?',(new_purchase,new_price,product_id))
    db.execute('INSERT INTO price_history(product_id,old_purchase,new_purchase,old_price,new_price,reason) VALUES(?,?,?,?,?,?)',(product_id,old_purchase,new_purchase,old_price,new_price,reason))
    db.execute('INSERT INTO price_rules(product_id,margin_percent,auto_update,last_purchase_price,last_selling_price,updated_at) VALUES(?,?,?,?,?,CURRENT_TIMESTAMP) ON CONFLICT(product_id) DO UPDATE SET last_purchase_price=excluded.last_purchase_price,last_selling_price=excluded.last_selling_price,updated_at=CURRENT_TIMESTAMP',(product_id,margin,1,new_purchase,new_price))
    return new_price

@app.after_request
def security_headers(response):
    response.headers["X-Content-Type-Options"]="nosniff"
    response.headers["X-Frame-Options"]="SAMEORIGIN"
    response.headers["Referrer-Policy"]="strict-origin-when-cross-origin"
    return response

@app.context_processor
def inject_store():
    return {"store_settings":settings_dict()}

@app.route("/")
def index():
    db=get_db()
    products=db.execute("""SELECT p.*,c.name category_name,
        COALESCE((SELECT AVG(r.rating) FROM reviews r WHERE r.product_id=p.id),0) rating,
        COALESCE((SELECT COUNT(*) FROM reviews r WHERE r.product_id=p.id),0) review_count
        FROM products p LEFT JOIN categories c ON c.id=p.category_id
        WHERE p.is_active=1 ORDER BY p.featured DESC,p.name""").fetchall()
    categories=db.execute("SELECT * FROM categories ORDER BY name").fetchall()
    active_offers=db.execute("""SELECT o.*,p.name FROM offers o JOIN products p ON p.id=o.product_id
        WHERE o.active=1 AND (o.ends_at IS NULL OR o.ends_at>=CURRENT_TIMESTAMP) ORDER BY o.id DESC""").fetchall()
    coupons=db.execute("""SELECT * FROM coupons WHERE active=1 AND (expires_at IS NULL OR expires_at>=CURRENT_TIMESTAMP)
        ORDER BY id DESC LIMIT 6""").fetchall()
    return render_template("index.html",products=products,categories=categories,offers=active_offers,coupons=coupons)

@app.route("/product/<int:product_id>")
def product(product_id):
    db=get_db()
    item=db.execute("""SELECT p.*,c.name category_name,
        COALESCE((SELECT AVG(r.rating) FROM reviews r WHERE r.product_id=p.id),0) rating,
        COALESCE((SELECT COUNT(*) FROM reviews r WHERE r.product_id=p.id),0) review_count
        FROM products p LEFT JOIN categories c ON c.id=p.category_id
        WHERE p.id=? AND p.is_active=1""",(product_id,)).fetchone()
    if not item:return "Product not found",404
    reviews=db.execute("SELECT * FROM reviews WHERE product_id=? ORDER BY id DESC LIMIT 20",(product_id,)).fetchall()
    related=db.execute("""SELECT * FROM products WHERE category_id=? AND id<>? AND is_active=1
        ORDER BY featured DESC,name LIMIT 6""",(item["category_id"],product_id)).fetchall()
    return render_template("product.html",product=item,reviews=reviews,related=related)

@app.route("/checkout",methods=["GET","POST"])
def checkout():
    if request.method=="POST":
        data=request.get_json(silent=True) or request.form
        name=str(data.get("customer_name","")).strip()
        phone=str(data.get("phone","")).strip()
        note=str(data.get("note","")).strip()
        delivery=str(data.get("delivery_type","Pickup"))
        address=str(data.get("address","")).strip()
        payment=str(data.get("payment_method","Pay at Store"))
        coupon_code=str(data.get("coupon_code","")).strip().upper()
        items=data.get("items",[])
        if isinstance(items,str):
            try: items=json.loads(items)
            except: items=[]
        if not name or not phone or not items:return jsonify(success=False,message="Name, mobile number and cart are required."),400
        if delivery not in ("Pickup","Delivery"):delivery="Pickup"
        if delivery=="Delivery" and not address:return jsonify(success=False,message="Address is required for home delivery."),400
        if payment not in ("Pay at Store","UPI"):payment="Pay at Store"
        db=get_db(); validated=[]; subtotal=0
        try:
            for item in items:
                pid=int(item["id"]); qty=int(item["quantity"])
                if qty<1:continue
                p=db.execute("SELECT * FROM products WHERE id=? AND is_active=1",(pid,)).fetchone()
                if not p:return jsonify(success=False,message="A product is no longer available."),400
                if p["stock"]<qty:return jsonify(success=False,message=f"Only {p['stock']} unit(s) of {p['name']} are available."),400
                sub=p["price"]*qty; subtotal+=sub; validated.append((p,qty,sub))
            if not validated:return jsonify(success=False,message="Your cart is empty."),400
            discount=0
            if coupon_code:
                c=db.execute("""SELECT * FROM coupons WHERE code=? AND active=1
                    AND (expires_at IS NULL OR expires_at>=CURRENT_TIMESTAMP)""",(coupon_code,)).fetchone()
                if not c:return jsonify(success=False,message="Invalid or expired coupon."),400
                if subtotal<c["min_order"]:return jsonify(success=False,message=f"Minimum order for this coupon is ₹{c['min_order']:.0f}."),400
                discount=min(subtotal*c["discount_percent"]/100,c["max_discount"] or subtotal)
            total=max(0,subtotal-discount)
            if delivery=="Delivery":
                charge=float(settings_dict().get("delivery_charge","0") or 0); total+=max(0,charge)
            points=int(total//100)
            cur=db.execute("""INSERT INTO orders(customer_name,phone,note,total,status,delivery_type,address,payment_method,
                coupon_code,discount,loyalty_earned) VALUES(?,?,?,?,?,?,?,?,?,?,?)""",
                (name,phone,note,total,"Received",delivery,address,payment,coupon_code,discount,points))
            oid=cur.lastrowid
            for p,q,sub in validated:
                db.execute("""INSERT INTO order_items(order_id,product_id,product_name,quantity,price,subtotal)
                    VALUES(?,?,?,?,?,?)""",(oid,p["id"],p["name"],q,p["price"],sub))
                db.execute("UPDATE products SET stock=stock-? WHERE id=?",(q,p["id"]))
            db.execute("""INSERT INTO customers(name,phone,loyalty_points) VALUES(?,?,?)
                ON CONFLICT(phone) DO UPDATE SET name=excluded.name,loyalty_points=customers.loyalty_points+excluded.loyalty_points""",
                (name,phone,points))
            db.execute("INSERT INTO order_status_history(order_id,status) VALUES(?,?)",(oid,"Received"))
            create_notification(db,oid,"Dashboard",f"New order #{oid} from {name} • ₹{total:.2f}")
            db.commit()
            return jsonify(success=True,order_id=oid,discount=discount,points=points)
        except Exception as e:
            db.rollback()
            return jsonify(success=False,message="Could not place order. Please try again."),500
    return render_template("checkout.html")

@app.route("/order/<int:order_id>")
def order_status(order_id):
    db=get_db()
    order=db.execute("SELECT * FROM orders WHERE id=?",(order_id,)).fetchone()
    if not order:return "Order not found",404
    items=db.execute("SELECT * FROM order_items WHERE order_id=?",(order_id,)).fetchall()
    history=db.execute("SELECT * FROM order_status_history WHERE order_id=? ORDER BY id",(order_id,)).fetchall()
    return render_template("order_status.html",order=order,items=items,history=history)

@app.route("/my-orders")
def my_orders():
    phone=session.get("customer_phone") or request.args.get("phone","").strip()
    db=get_db()
    orders=db.execute("SELECT * FROM orders WHERE phone=? ORDER BY created_at DESC",(phone,)).fetchall() if phone else []
    customer=db.execute("SELECT * FROM customers WHERE phone=?",(phone,)).fetchone() if phone else None
    return render_template("my_orders.html",orders=orders,phone=phone,customer=customer)

@app.route("/api/order/<int:order_id>")
def api_order(order_id):
    db=get_db(); o=db.execute("SELECT * FROM orders WHERE id=?",(order_id,)).fetchone()
    if not o:return jsonify(success=False,message="Order not found"),404
    items=db.execute("SELECT * FROM order_items WHERE order_id=?",(order_id,)).fetchall()
    hist=db.execute("SELECT status,created_at FROM order_status_history WHERE order_id=? ORDER BY id",(order_id,)).fetchall()
    return jsonify(success=True,order=dict(o),items=[dict(x) for x in items],history=[dict(x) for x in hist])

@app.route("/invoice/<int:order_id>")
def invoice(order_id):
    db=get_db(); o=db.execute("SELECT * FROM orders WHERE id=?",(order_id,)).fetchone()
    if not o:return "Order not found",404
    items=db.execute("SELECT * FROM order_items WHERE order_id=?",(order_id,)).fetchall(); s=settings_dict()
    buf=BytesIO(); pdf=canvas.Canvas(buf,pagesize=A4); w,h=A4; y=h-55
    pdf.setFont("Helvetica-Bold",18); pdf.drawString(45,y,s.get("store_name","OM KIRANA STORE")); y-=22
    pdf.setFont("Helvetica",10); pdf.drawString(45,y,s.get("address","")[:100]); y-=15; pdf.drawString(45,y,"Phone: "+s.get("store_phone","")); y-=25
    pdf.setFont("Helvetica-Bold",12); pdf.drawString(45,y,f"Invoice / Order #{order_id}"); y-=18
    pdf.setFont("Helvetica",10); pdf.drawString(45,y,f"Customer: {o['customer_name']}"); y-=15; pdf.drawString(45,y,f"Mobile: {o['phone']}"); y-=15
    pdf.drawString(45,y,f"Date: {o['created_at']}"); y-=25
    pdf.setFont("Helvetica-Bold",10); pdf.drawString(45,y,"Item"); pdf.drawString(330,y,"Qty"); pdf.drawString(380,y,"Price"); pdf.drawString(455,y,"Subtotal"); y-=16
    pdf.setFont("Helvetica",10)
    for it in items:
        if y<70:pdf.showPage();y=h-55
        pdf.drawString(45,y,str(it["product_name"])[:42]);pdf.drawRightString(350,y,str(it["quantity"]))
        pdf.drawRightString(430,y,f"₹{it['price']:.2f}");pdf.drawRightString(535,y,f"₹{it['subtotal']:.2f}");y-=17
    y-=8;pdf.setFont("Helvetica-Bold",11);pdf.drawRightString(535,y,f"Discount: ₹{o['discount']:.2f}");y-=18
    pdf.drawRightString(535,y,f"TOTAL: ₹{o['total']:.2f}");pdf.save();buf.seek(0)
    return send_file(buf,as_attachment=False,download_name=f"OM-KIRANA-Invoice-{order_id}.pdf",mimetype="application/pdf")

@app.route("/api/reorder/<int:order_id>",methods=["POST"])
def reorder(order_id):
    db=get_db(); old=db.execute("SELECT * FROM order_items WHERE order_id=?",(order_id,)).fetchall(); cart=[]
    for it in old:
        p=db.execute("SELECT id,name,price,stock FROM products WHERE id=? AND is_active=1",(it["product_id"],)).fetchone()
        if p and p["stock"]>0:cart.append({"id":p["id"],"name":p["name"],"price":p["price"],"stock":p["stock"],"quantity":min(it["quantity"],p["stock"])})
    return jsonify(success=True,items=cart)

@app.route("/login",methods=["GET","POST"])
def customer_login():
    next_url=request.args.get("next") or request.form.get("next") or url_for("index")
    if request.method=="POST":
        action=request.form.get("action","send")
        phone=request.form.get("phone","").strip(); name=request.form.get("name","").strip() or "Customer"
        if not phone.isdigit() or len(phone)!=10:
            flash("Enter a valid 10-digit mobile number.","error"); return render_template("customer_login.html",next=next_url,otp_sent=False)
        if action=="verify":
            code=request.form.get("otp","").strip(); pending=session.get("otp_phone")
            db=get_db(); row=db.execute("SELECT code,expires_at FROM login_codes WHERE phone=?",(phone,)).fetchone()
            valid=row and pending==phone and row["code"]==code and datetime.fromisoformat(row["expires_at"])>datetime.utcnow()
            if not valid:
                flash("Invalid or expired OTP. Please request a new OTP.","error"); return render_template("customer_login.html",next=next_url,otp_sent=True,phone=phone,name=name)
            session.pop("otp_phone",None); session["customer_phone"]=phone; session["customer_name"]=name
            db.execute("INSERT INTO customers(name,phone) VALUES(?,?) ON CONFLICT(phone) DO UPDATE SET name=excluded.name",(name,phone)); db.commit()
            flash("Mobile number verified successfully.","success"); return redirect(next_url)
        import random
        code=f"{random.randint(0,999999):06d}"; expires=(datetime.utcnow()+timedelta(minutes=5)).isoformat()
        db=get_db(); db.execute("INSERT INTO login_codes(phone,code,expires_at) VALUES(?,?,?) ON CONFLICT(phone) DO UPDATE SET code=excluded.code,expires_at=excluded.expires_at",(phone,code,expires)); db.commit()
        session["otp_phone"]=phone
        # Local portfolio/demo mode: show OTP on screen. For live SMS, connect an SMS provider here.
        flash(f"Demo OTP for +91 {phone}: {code} (valid for 5 minutes)","success")
        return render_template("customer_login.html",next=next_url,otp_sent=True,phone=phone,name=name)
    return render_template("customer_login.html",next=next_url,otp_sent=False)

@app.route("/logout")
def customer_logout():session.pop("customer_phone",None);session.pop("customer_name",None);return redirect(url_for("index"))

@app.route("/profile")
def profile():
    phone=session.get("customer_phone")
    if not phone:return redirect(url_for("customer_login",next=url_for("profile")))
    db=get_db(); c=db.execute("SELECT * FROM customers WHERE phone=?",(phone,)).fetchone()
    orders=db.execute("SELECT COUNT(*) n FROM orders WHERE phone=?",(phone,)).fetchone()["n"]
    return render_template("profile.html",customer=c,order_count=orders)

@app.route("/favorites")
def favorites():
    phone=session.get("customer_phone")
    if not phone:return redirect(url_for("customer_login",next=url_for("favorites")))
    db=get_db(); products=db.execute("""SELECT p.* FROM products p JOIN favorites f ON f.product_id=p.id
        WHERE f.customer_phone=? AND p.is_active=1 ORDER BY p.name""",(phone,)).fetchall()
    return render_template("favorites.html",products=products)

@app.route("/api/favorite/<int:product_id>",methods=["POST"])
def toggle_favorite(product_id):
    phone=session.get("customer_phone")
    if not phone:return jsonify(success=False,login=True),401
    db=get_db(); row=db.execute("SELECT id FROM favorites WHERE customer_phone=? AND product_id=?",(phone,product_id)).fetchone()
    if row:db.execute("DELETE FROM favorites WHERE id=?",(row["id"],));active=False
    else:db.execute("INSERT OR IGNORE INTO favorites(customer_phone,product_id) VALUES(?,?)",(phone,product_id));active=True
    db.commit();return jsonify(success=True,active=active)

@app.route("/api/review",methods=["POST"])
def add_review():
    data=request.get_json(silent=True) or {}; pid=int(data.get("product_id",0) or 0); rating=int(data.get("rating",0) or 0)
    text=str(data.get("text","")).strip()[:500]; phone=session.get("customer_phone",""); name=session.get("customer_name","Customer")
    if not pid or not 1<=rating<=5:return jsonify(success=False,message="Choose a rating from 1 to 5."),400
    db=get_db();db.execute("INSERT INTO reviews(product_id,customer_name,phone,rating,text) VALUES(?,?,?,?,?)",(pid,name,phone,rating,text));db.commit()
    return jsonify(success=True)

@app.route("/api/reviews/<int:product_id>")
def reviews_api(product_id):
    db=get_db();rows=db.execute("SELECT customer_name,rating,text,created_at FROM reviews WHERE product_id=? ORDER BY id DESC LIMIT 30",(product_id,)).fetchall()
    return jsonify(reviews=[dict(r) for r in rows])

@app.route("/api/recommendations/<int:product_id>")
def recommendations(product_id):
    db=get_db();p=db.execute("SELECT category_id FROM products WHERE id=?",(product_id,)).fetchone()
    if not p:return jsonify(products=[])
    rows=db.execute("""SELECT id,name,price,stock,image FROM products WHERE category_id=? AND id<>? AND is_active=1
        ORDER BY featured DESC,name LIMIT 8""",(p["category_id"],product_id)).fetchall()
    return jsonify(products=[dict(x) for x in rows])

@app.route("/api/products")
def api_products():
    db=get_db(); rows=db.execute("""SELECT p.id,p.name,p.price,p.purchase_price,p.stock,p.unit,p.barcode,p.image,p.description,p.offer,c.name category
        FROM products p LEFT JOIN categories c ON c.id=p.category_id WHERE p.is_active=1 ORDER BY p.name""").fetchall()
    return jsonify([dict(x) for x in rows])

@app.route("/api/barcode/<barcode>")
def barcode_lookup(barcode):
    db=get_db();p=db.execute("""SELECT p.*,c.name category FROM products p LEFT JOIN categories c ON c.id=p.category_id
        WHERE p.barcode=? AND p.is_active=1""",(barcode.strip(),)).fetchone()
    return (jsonify(success=True,product=dict(p)) if p else jsonify(success=False,message="Product not found for this barcode.")), (200 if p else 404)

@app.route("/api/coupon",methods=["POST"])
def coupon_check():
    code=str((request.get_json(silent=True) or {}).get("code","")).strip().upper()
    db=get_db();c=db.execute("""SELECT * FROM coupons WHERE code=? AND active=1
        AND (expires_at IS NULL OR expires_at>=CURRENT_TIMESTAMP)""",(code,)).fetchone()
    if not c:return jsonify(success=False,message="Invalid or expired coupon."),400
    return jsonify(success=True,discount_percent=c["discount_percent"],max_discount=c["max_discount"],min_order=c["min_order"])

@app.route("/admin/login",methods=["GET","POST"])
def admin_login():
    if request.method=="POST":
        if request.form.get("username","").strip()=="admin" and request.form.get("password","")=="admin123":
            session["admin_logged_in"]=True;return redirect(url_for("admin_dashboard"))
        flash("Invalid username or password.","error")
    return render_template("admin_login.html")

@app.route("/admin/logout")
def admin_logout():session.clear();return redirect(url_for("index"))

@app.route("/admin")
@admin_required
def admin_dashboard():
    db=get_db()
    stats={
        "products":db.execute("SELECT COUNT(*) n FROM products WHERE is_active=1").fetchone()["n"],
        "orders":db.execute("SELECT COUNT(*) n FROM orders").fetchone()["n"],
        "pending":db.execute("SELECT COUNT(*) n FROM orders WHERE status IN ('Received','Accepted','Preparing')").fetchone()["n"],
        "low_stock":db.execute("SELECT COUNT(*) n FROM products WHERE is_active=1 AND stock<=CAST((SELECT value FROM settings WHERE key='low_stock_limit') AS INTEGER)").fetchone()["n"],
        "sales":db.execute("SELECT COALESCE(SUM(total),0) n FROM orders WHERE status!='Cancelled'").fetchone()["n"],
        "profit":db.execute("""SELECT COALESCE(SUM(oi.subtotal-(p.purchase_price*oi.quantity)),0) n FROM order_items oi
            JOIN orders o ON o.id=oi.order_id JOIN products p ON p.id=oi.product_id WHERE o.status!='Cancelled'""").fetchone()["n"],
        "expenses":db.execute("SELECT COALESCE(SUM(amount),0) n FROM expenses").fetchone()["n"]
    }
    stats["net_profit"]=stats["profit"]-stats["expenses"]
    recent=db.execute("SELECT * FROM orders ORDER BY id DESC LIMIT 10").fetchall()
    daily=db.execute("""SELECT substr(created_at,1,10) day,COALESCE(SUM(total),0) sales,COUNT(*) orders FROM orders
        WHERE status!='Cancelled' GROUP BY day ORDER BY day DESC LIMIT 7""").fetchall()
    notification_count=db.execute("SELECT COUNT(*) n FROM notifications WHERE status='Pending'").fetchone()["n"]
    low=db.execute("SELECT * FROM products WHERE is_active=1 AND stock<=10 ORDER BY stock,name LIMIT 8").fetchall()
    return render_template("admin_dashboard.html",stats=stats,recent=recent,daily=daily,low=low,notification_count=notification_count)

def save_upload(uploaded):
    if not uploaded or not uploaded.filename:return ""
    ext=Path(uploaded.filename).suffix.lower()
    if ext not in {".jpg",".jpeg",".png",".webp"}:raise ValueError("Use JPG, PNG or WEBP image.")
    filename=secure_filename(datetime.now().strftime("%Y%m%d%H%M%S%f")+ext);uploaded.save(UPLOAD_FOLDER/filename)
    return "uploads/"+filename

@app.route("/admin/products",methods=["GET","POST"])
@admin_required
def admin_products():
    db=get_db()
    if request.method=="POST":
        try:
            name=request.form.get("name","").strip();category_id=int(request.form.get("category_id","0") or 0) or None
            purchase=float(request.form.get("purchase_price","0") or 0);selling=float(request.form.get("selling_price","0") or 0)
            stock=int(request.form.get("stock","0") or 0);unit=request.form.get("unit","").strip()
            barcode=request.form.get("barcode","").strip();description=request.form.get("description","").strip();offer=request.form.get("offer","").strip()
            image=save_upload(request.files.get("image"))
            if not name or purchase<0 or selling<0 or stock<0:raise ValueError("Please enter valid product details.")
            db.execute("""INSERT INTO products(name,category_id,price,purchase_price,stock,unit,barcode,image,description,offer)
                VALUES(?,?,?,?,?,?,?,?,?,?)""",(name,category_id,selling,purchase,stock,unit,barcode,image,description,offer))
            db.commit();flash("Product added successfully. Customer side updated automatically.","success")
        except Exception as e:flash(str(e),"error")
        return redirect(url_for("admin_products"))
    products=db.execute("SELECT p.*,c.name category_name FROM products p LEFT JOIN categories c ON c.id=p.category_id ORDER BY p.id DESC").fetchall()
    cats=db.execute("SELECT * FROM categories ORDER BY name").fetchall()
    return render_template("admin_products.html",products=products,categories=cats)

@app.route("/admin/products/<int:product_id>/update",methods=["POST"])
@admin_required
def update_product(product_id):
    db=get_db()
    try:
        selling=float(request.form.get("price","0"));purchase=float(request.form.get("purchase_price","0"))
        stock=int(request.form.get("stock","0"));active=1 if request.form.get("active")=="1" else 0
        featured=1 if request.form.get("featured")=="1" else 0
        oldp=db.execute("SELECT purchase_price,price FROM products WHERE id=?",(product_id,)).fetchone()
        auto=request.form.get("auto_price") == "1"
        if auto and oldp and abs(float(oldp["purchase_price"])-purchase)>0.0001:
            calculated=apply_auto_price(db,product_id,purchase,"Automatic purchase-price update")
            if calculated is not None: selling=calculated
        db.execute("""UPDATE products SET price=?,purchase_price=?,stock=?,featured=?,is_active=?,
            barcode=?,description=?,offer=? WHERE id=?""",
            (selling,purchase,stock,featured,active,request.form.get("barcode","").strip(),
             request.form.get("description","").strip(),request.form.get("offer","").strip(),product_id))
        db.commit();flash("Product updated.","success")
    except:flash("Invalid product values.","error")
    return redirect(url_for("admin_products"))

@app.route("/admin/products/bulk-update",methods=["POST"])
@admin_required
def bulk_update():
    db=get_db(); changed=0
    try:
        for pid in request.form.getlist("product_id"):
            price=request.form.get(f"price_{pid}");stock=request.form.get(f"stock_{pid}")
            if price is not None and stock is not None:
                db.execute("UPDATE products SET price=?,stock=? WHERE id=?",(float(price),int(stock),int(pid)));changed+=1
        db.commit();flash(f"{changed} product(s) updated.","success")
    except:db.rollback();flash("Bulk update failed.","error")
    return redirect(url_for("admin_products"))

@app.route("/admin/inventory")
@admin_required
def admin_inventory():
    db=get_db();products=db.execute("SELECT p.*,c.name category_name FROM products p LEFT JOIN categories c ON c.id=p.category_id WHERE p.is_active=1 ORDER BY p.stock,p.name").fetchall()
    return render_template("admin_inventory.html",products=products)

@app.route("/admin/inventory/<int:product_id>/stock",methods=["POST"])
@admin_required
def inventory_update(product_id):
    try:stock=max(0,int(request.form.get("stock","0")))
    except:stock=0
    db=get_db();db.execute("UPDATE products SET stock=? WHERE id=?",(stock,product_id));db.commit();flash("Stock updated.","success")
    return redirect(url_for("admin_inventory"))

@app.route("/admin/orders")
@admin_required
def admin_orders():
    db=get_db();orders=db.execute("SELECT * FROM orders ORDER BY id DESC").fetchall()
    return render_template("admin_orders.html",orders=orders)

@app.route("/admin/orders/<int:order_id>/status",methods=["POST"])
@admin_required
def update_order_status(order_id):
    status=request.form.get("status","");allowed={"Received","Accepted","Preparing","Ready for Pickup","Out for Delivery","Collected","Delivered","Cancelled"}
    if status not in allowed:flash("Invalid status.","error");return redirect(url_for("admin_orders"))
    db=get_db();db.execute("UPDATE orders SET status=? WHERE id=?",(status,order_id));db.execute("INSERT INTO order_status_history(order_id,status) VALUES(?,?)",(order_id,status))
    if status in ("Ready for Pickup","Out for Delivery","Delivered"):create_notification(db,order_id,"Customer",f"Order #{order_id} status: {status}")
    db.commit();flash("Order status updated.","success");return redirect(url_for("admin_orders"))

@app.route("/admin/notifications")
@admin_required
def admin_notifications():
    db=get_db();rows=db.execute("SELECT * FROM notifications ORDER BY id DESC LIMIT 100").fetchall()
    return render_template("admin_notifications.html",notifications=rows)

@app.route("/admin/notifications/<int:notification_id>/done",methods=["POST"])
@admin_required
def notification_done(notification_id):
    db=get_db();db.execute("UPDATE notifications SET status='Sent' WHERE id=?",(notification_id,));db.commit();return redirect(url_for("admin_notifications"))

@app.route("/admin/offers",methods=["GET","POST"])
@admin_required
def admin_offers():
    db=get_db()
    if request.method=="POST":
        pid=int(request.form["product_id"]);discount=float(request.form["discount"]);days=max(1,int(request.form.get("days",7)))
        ends=(datetime.now()+timedelta(days=days)).strftime("%Y-%m-%d %H:%M:%S")
        db.execute("INSERT INTO offers(product_id,discount_percent,ends_at,active) VALUES(?,?,?,1)",(pid,discount,ends));db.commit();flash("Offer created.","success");return redirect(url_for("admin_offers"))
    offers=db.execute("SELECT o.*,p.name FROM offers o JOIN products p ON p.id=o.product_id ORDER BY o.id DESC").fetchall()
    products=db.execute("SELECT id,name,price FROM products WHERE is_active=1 ORDER BY name").fetchall()
    coupons=db.execute("SELECT * FROM coupons ORDER BY id DESC").fetchall()
    return render_template("admin_offers.html",offers=offers,products=products,coupons=coupons)

@app.route("/admin/coupons",methods=["POST"])
@admin_required
def create_coupon():
    db=get_db()
    try:
        code=request.form.get("code","").strip().upper();pct=float(request.form.get("discount_percent","0"));mx=float(request.form.get("max_discount","0"));mn=float(request.form.get("min_order","0"));days=int(request.form.get("days","30"))
        if not code or pct<=0 or pct>100:raise ValueError
        exp=(datetime.now()+timedelta(days=days)).strftime("%Y-%m-%d %H:%M:%S")
        db.execute("INSERT INTO coupons(code,discount_percent,max_discount,min_order,expires_at) VALUES(?,?,?,?,?)",(code,pct,mx,mn,exp));db.commit();flash("Coupon created.","success")
    except:db.rollback();flash("Coupon could not be created (code may already exist).","error")
    return redirect(url_for("admin_offers"))

@app.route("/admin/coupons/<int:coupon_id>/toggle",methods=["POST"])
@admin_required
def toggle_coupon(coupon_id):
    db=get_db();db.execute("UPDATE coupons SET active=CASE WHEN active=1 THEN 0 ELSE 1 END WHERE id=?",(coupon_id,));db.commit();return redirect(url_for("admin_offers"))

@app.route("/admin/analytics")
@admin_required
def admin_analytics():
    db=get_db()
    daily=db.execute("""SELECT substr(created_at,1,10) day,COUNT(*) orders,COALESCE(SUM(total),0) sales FROM orders
        WHERE status!='Cancelled' GROUP BY day ORDER BY day DESC LIMIT 30""").fetchall()
    popular=db.execute("""SELECT product_name,SUM(quantity) qty,COALESCE(SUM(subtotal),0) revenue FROM order_items
        GROUP BY product_name ORDER BY qty DESC LIMIT 15""").fetchall()
    return render_template("admin_analytics.html",daily=daily,popular=popular)

@app.route("/admin/expenses",methods=["GET","POST"])
@admin_required
def expense_manager():
    db=get_db()
    if request.method=="POST":
        try:db.execute("INSERT INTO expenses(title,amount,category) VALUES(?,?,?)",(request.form.get("title","").strip(),float(request.form.get("amount","0")),request.form.get("category","Other")));db.commit();flash("Expense added.","success")
        except:db.rollback();flash("Invalid expense.","error")
        return redirect(url_for("expense_manager"))
    rows=db.execute("SELECT * FROM expenses ORDER BY id DESC").fetchall();total=db.execute("SELECT COALESCE(SUM(amount),0) total FROM expenses").fetchone()["total"]
    return render_template("admin_expenses.html",expenses=rows,total=total)


@app.route("/admin/reviews")
@admin_required
def admin_reviews():
    db=get_db()
    rows=db.execute("""SELECT r.*,p.name product_name FROM reviews r LEFT JOIN products p ON p.id=r.product_id
        ORDER BY r.id DESC""").fetchall()
    return render_template("admin_reviews.html",reviews=rows)

@app.route("/admin/reviews/<int:review_id>/delete",methods=["POST"])
@admin_required
def delete_review(review_id):
    db=get_db();db.execute("DELETE FROM reviews WHERE id=?",(review_id,));db.commit();flash("Review removed.","success")
    return redirect(url_for("admin_reviews"))

@app.route("/admin/customers")
@admin_required
def admin_customers():
    db=get_db()
    rows=db.execute("""SELECT c.*,COUNT(o.id) order_count,COALESCE(SUM(o.total),0) spent
        FROM customers c LEFT JOIN orders o ON o.phone=c.phone AND o.status!='Cancelled'
        GROUP BY c.id ORDER BY c.id DESC""").fetchall()
    return render_template("admin_customers.html",customers=rows)

@app.route("/admin/settings",methods=["GET","POST"])
@admin_required
def admin_settings():
    db=get_db()
    if request.method=="POST":
        keys=["store_name","store_phone","whatsapp","address","upi_id","public_url","opening_time","closing_time","delivery_charge","low_stock_limit"]
        for k in keys:db.execute("INSERT INTO settings(key,value) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",(k,request.form.get(k,"").strip()))
        db.commit();flash("Store settings saved.","success")
    return render_template("admin_settings.html",settings=settings_dict())

@app.route("/admin/qr")
@admin_required
def admin_qr():
    s=settings_dict();public_url=request.args.get("url") or s.get("public_url") or request.host_url
    qrcode.make(public_url).save(Path(app.root_path)/"static"/"om-kirana-qr.png")
    return render_template("admin_qr.html",public_url=public_url)

@app.route("/admin/export/orders.csv")
@admin_required
def export_orders():
    db=get_db();rows=db.execute("SELECT id,customer_name,phone,total,status,delivery_type,payment_method,created_at FROM orders ORDER BY id DESC").fetchall()
    out=StringIO();w=writer(out);w.writerow(["Order ID","Customer","Phone","Total","Status","Type","Payment","Created At"])
    for r in rows:w.writerow(list(r))
    return Response(out.getvalue(),mimetype="text/csv",headers={"Content-Disposition":"attachment; filename=om-kirana-orders.csv"})

@app.route("/admin/export/products.csv")
@admin_required
def export_products():
    db=get_db();rows=db.execute("SELECT id,name,price,purchase_price,stock,barcode FROM products ORDER BY name").fetchall()
    out=StringIO();w=writer(out);w.writerow(["ID","Product","Selling Price","Purchase Price","Stock","Barcode"])
    for r in rows:w.writerow(list(r))
    return Response(out.getvalue(),mimetype="text/csv",headers={"Content-Disposition":"attachment; filename=om-kirana-products.csv"})

@app.route("/admin/price-center")
@admin_required
def price_center():
    db=get_db()
    rows=db.execute("""SELECT p.id,p.name,p.purchase_price,p.price,p.stock,
        COALESCE(r.margin_percent, CAST((SELECT value FROM settings WHERE key='default_margin_percent') AS REAL),12) margin_percent,
        COALESCE(r.auto_update,1) auto_update
        FROM products p LEFT JOIN price_rules r ON r.product_id=p.id WHERE p.is_active=1 ORDER BY p.name""").fetchall()
    history=db.execute("""SELECT h.*,p.name FROM price_history h JOIN products p ON p.id=h.product_id ORDER BY h.id DESC LIMIT 100""").fetchall()
    return render_template("admin_price_center.html",products=rows,history=history)

@app.route("/admin/price-center/<int:product_id>",methods=["POST"])
@admin_required
def price_rule_update(product_id):
    db=get_db()
    margin=max(0,float(request.form.get("margin_percent","12") or 12)); auto=1 if request.form.get("auto_update")=="1" else 0
    p=db.execute("SELECT purchase_price,price FROM products WHERE id=?",(product_id,)).fetchone()
    if not p:return redirect(url_for('price_center'))
    db.execute("INSERT INTO price_rules(product_id,margin_percent,auto_update,last_purchase_price,last_selling_price) VALUES(?,?,?,?,?) ON CONFLICT(product_id) DO UPDATE SET margin_percent=excluded.margin_percent,auto_update=excluded.auto_update",(product_id,margin,auto,p['purchase_price'],p['price']))
    if auto: apply_auto_price(db,product_id,p['purchase_price'],'Automatic margin rule')
    db.commit(); flash('Automatic price rule saved.','success'); return redirect(url_for('price_center'))

@app.route("/api/price-update/<int:product_id>",methods=["POST"])
@admin_required
def api_price_update(product_id):
    data=request.get_json(silent=True) or {}; purchase=float(data.get('purchase_price',0) or 0)
    if purchase<0:return jsonify(success=False,message='Invalid purchase price'),400
    db=get_db(); price=apply_auto_price(db,product_id,purchase,'API price update'); db.commit()
    return jsonify(success=price is not None,new_price=price)

@app.route("/api/price-history/<int:product_id>")
@admin_required
def api_price_history(product_id):
    db=get_db(); rows=db.execute('SELECT old_purchase,new_purchase,old_price,new_price,reason,created_at FROM price_history WHERE product_id=? ORDER BY id DESC LIMIT 50',(product_id,)).fetchall()
    return jsonify(history=[dict(r) for r in rows])

@app.route("/admin/notification-center")
@admin_required
def notification_center():
    db=get_db(); rows=db.execute('SELECT * FROM notifications ORDER BY id DESC LIMIT 200').fetchall()
    return render_template('admin_notification_center.html',notifications=rows,settings=settings_dict())

@app.route("/admin/notification-center/test",methods=['POST'])
@admin_required
def notification_test():
    db=get_db(); phone=request.form.get('phone','').strip(); msg=request.form.get('message','Test notification from OM KIRANA STORE').strip()
    db.execute("INSERT INTO notifications(order_id,channel,message,status) VALUES(NULL,'SMS',?,'Queued')",(msg,))
    db.execute("INSERT INTO notifications(order_id,channel,message,status) VALUES(NULL,'WhatsApp',?,'Queued')",(msg,))
    db.commit(); flash('SMS + WhatsApp notification queued. Connect provider credentials for real delivery.','success'); return redirect(url_for('notification_center'))

@app.route("/admin/daily-report")
@admin_required
def daily_report():
    db=get_db(); today=datetime.now().strftime('%Y-%m-%d')
    sales=db.execute("SELECT COALESCE(SUM(total),0) n FROM orders WHERE substr(created_at,1,10)=? AND status!='Cancelled'",(today,)).fetchone()['n']
    orders=db.execute("SELECT COUNT(*) n FROM orders WHERE substr(created_at,1,10)=? AND status!='Cancelled'",(today,)).fetchone()['n']
    profit=db.execute("""SELECT COALESCE(SUM(oi.subtotal-(p.purchase_price*oi.quantity)),0) n FROM order_items oi JOIN orders o ON o.id=oi.order_id JOIN products p ON p.id=oi.product_id WHERE substr(o.created_at,1,10)=? AND o.status!='Cancelled'""",(today,)).fetchone()['n']
    expenses=db.execute("SELECT COALESCE(SUM(amount),0) n FROM expenses WHERE substr(created_at,1,10)=?",(today,)).fetchone()['n']
    low=db.execute("SELECT COUNT(*) n FROM products WHERE is_active=1 AND stock<=CAST((SELECT value FROM settings WHERE key='low_stock_limit') AS INTEGER)").fetchone()['n']
    return jsonify(date=today,orders=orders,sales=sales,estimated_profit=profit,expenses=expenses,net_profit=profit-expenses,low_stock=low)

@app.route("/api/addresses",methods=['GET','POST','DELETE'])
def addresses():
    phone=session.get('customer_phone')
    if not phone:return jsonify(success=False,login=True),401
    db=get_db()
    if request.method=='POST':
        data=request.get_json(silent=True) or {}; addr=str(data.get('address','')).strip(); label=str(data.get('label','Home')).strip()[:30]
        if not addr:return jsonify(success=False,message='Address required'),400
        db.execute('UPDATE saved_addresses SET is_default=0 WHERE customer_phone=?',(phone,)); db.execute('INSERT INTO saved_addresses(customer_phone,label,address,is_default) VALUES(?,?,?,1)',(phone,label,addr)); db.commit(); return jsonify(success=True)
    rows=db.execute('SELECT * FROM saved_addresses WHERE customer_phone=? ORDER BY is_default DESC,id DESC',(phone,)).fetchall(); return jsonify(addresses=[dict(r) for r in rows])

@app.route("/api/search")
def smart_search():
    q=request.args.get('q','').strip(); cat=request.args.get('category','').strip(); db=get_db()
    sql="""SELECT p.*,c.name category_name,COALESCE((SELECT AVG(r.rating) FROM reviews r WHERE r.product_id=p.id),0) rating FROM products p LEFT JOIN categories c ON c.id=p.category_id WHERE p.is_active=1"""; args=[]
    if q:
        sql += " AND (p.name LIKE ? OR p.description LIKE ? OR p.barcode LIKE ? OR c.name LIKE ?)"; like='%'+q+'%'; args += [like,like,like,like]
    if cat: sql += ' AND c.name=?'; args.append(cat)
    sql += ' ORDER BY p.featured DESC,p.name LIMIT 100'
    rows=db.execute(sql,args).fetchall(); return jsonify(products=[dict(r) for r in rows])

@app.route("/smart-tools")
def smart_tools():return render_template("smart_tools.html")

if __name__=="__main__":
    app.run(debug=True)
