from flask import Flask, render_template, request, send_file, jsonify
import pdfkit, io, base64, datetime, os, uuid
from odoo_client import OdooClient

# ---------------- Flask App ----------------
app = Flask(__name__)
odoo = OdooClient()

# ---------------- PDFKit Config ----------------
if os.getenv("RENDER"):
    PDFKIT_CONFIG = pdfkit.configuration(wkhtmltopdf="/usr/bin/wkhtmltopdf")
else:
    PDFKIT_CONFIG = pdfkit.configuration(
        wkhtmltopdf=r"C:\Program Files\wkhtmltopdf\bin\wkhtmltopdf.exe"
    )

# ---------------- ROUTES ----------------

@app.route("/rfq/<int:lead_id>", methods=["GET"])
def rfq_form(lead_id):
    """Render RFQ Form"""
    project_name = request.args.get("project_name", "")
    description = request.args.get("project_description", "")
    category = request.args.get("project_category", "")
    return render_template("rfq_form.html",
                           lead_id=lead_id,
                           project_name=project_name,
                           description=description,
                           category=category)


@app.route("/submit-rfq", methods=["POST"])
def submit_rfq():
    """Generate PDF from RFQ form and attach to Odoo chatter"""
    lead_id = int(request.form.get("lead_id", 0))
    if not lead_id:
        return "Invalid lead_id", 400

    # Fetch lead data from Odoo
    lead = odoo.models.execute_kw(
        odoo.DB, odoo.uid, odoo.PASSWORD,
        'crm.lead', 'read', [[lead_id]],
        {'fields': ['name', 'partner_name', 'email_from', 'phone',
                    'x_studio_project_name_1', 'x_studio_project_description_1', 'x_studio_project_category_1']}
    )[0]

    client_name = request.form.get("client_name") or lead.get('partner_name', 'Client')
    client_address = request.form.get("client_address") or ""
    client_email = request.form.get("client_email") or lead.get('email_from', 'client@example.com')
    client_phone = request.form.get("client_phone") or lead.get('phone', '')
    expiration_date = request.form.get("expiration_date") or (datetime.date.today() + datetime.timedelta(days=15)).strftime("%m/%d/%Y")

    # Project fields
    field_names = request.form.getlist("field_name[]")
    field_values = request.form.getlist("field_value[]")
    quantities = request.form.getlist("quantity[]")
    unit_prices = request.form.getlist("unit_price[]")

    subtotal = 0
    rows = ""
    for name, value, qty, price in zip(field_names, field_values, quantities, unit_prices):
        try:
            qty_val = int(qty)
            price_val = float(price)
        except:
            qty_val = 1
            price_val = 0
        line_total = qty_val * price_val
        subtotal += line_total
        desc = f"{name}: {value}"
        rows += f"<tr><td>{qty_val}</td><td>{desc}</td><td>${price_val:.2f}</td><td>${line_total:.2f}</td></tr>"

    total = subtotal
    quotation_number = f"QT-{str(uuid.uuid4())[:8].upper()}"
    date_today = datetime.date.today().strftime("%m/%d/%Y")

    # Convert logo to base64
    with open("static/logo.jpg", "rb") as img_file:
        logo_base64 = base64.b64encode(img_file.read()).decode('utf-8')

    # Create PDF HTML
    pdf_html = f"""
    <html>
    <head>
    <style>
        body {{ font-family: 'Times New Roman', serif; font-size: 14px; line-height: 1.5; margin: 40px; }}
        table {{ width:100%; border-collapse: collapse; margin-top: 10px; }}
        th, td {{ border: 1px solid #ccc; padding: 8px; text-align: left; }}
        th {{ background: #f4f4f4; }}
        .header-table td {{ border:none; vertical-align: top; }}
    </style>
    </head>
    <body>
    <table class="header-table">
        <tr>
            <td><img src="data:image/jpeg;base64,{logo_base64}" style="width:150px;height:auto;"></td>
            <td style="text-align:right;">
                <h2>Strategic Value Solutions</h2>
                <p>QUOTE<br>QUOTATION #: {quotation_number}<br>Date: {date_today}<br>Expiration: {expiration_date}</p>
            </td>
        </tr>
    </table>

    <h4>To:</h4>
    <p><b>{client_name}</b><br>{client_address}<br>{client_email}<br>{client_phone}</p>

    <table>
        <tr><th>Qty</th><th>Description</th><th>Unit Price</th><th>Line Total</th></tr>
        {rows}
    </table>

    <table style="margin-top:20px;">
        <tr><td style="text-align:right;"><b>Subtotal:</b></td><td style="text-align:right;">${subtotal:.2f}</td></tr>
        <tr><td style="text-align:right;"><b>Sales Tax:</b></td><td style="text-align:right;">$0.00</td></tr>
        <tr><td style="text-align:right;"><b>Total:</b></td><td style="text-align:right;"><b>${total:.2f}</b></td></tr>
    </table>

    <p style="margin-top:20px;">Quotation prepared by: <b>Uttam Soni</b></p>
    <p>This is a quotation on the goods named, subject to the conditions noted below: All sales final, payment due upon receipt.</p>
    <p>To accept this quotation, sign here and return: ________________________________________________</p>
    <p>Thank you for your business!</p>
    </body>
    </html>
    """

    # Generate PDF
    try:
        pdf_bytes = pdfkit.from_string(pdf_html, False, configuration=PDFKIT_CONFIG)
    except Exception as e:
        return f"PDF generation failed: {e}", 500

    pdf_filename = f"Quotation_{lead_id}.pdf"

    # -------------------- Upload PDF to Odoo chatter --------------------
    try:
        pdf_base64 = base64.b64encode(pdf_bytes).decode('utf-8')

        # Create attachment
        attachment_id = odoo.models.execute_kw(
            odoo.DB, odoo.uid, odoo.PASSWORD,
            'ir.attachment', 'create',
            [{
                'name': pdf_filename,
                'datas': pdf_base64,
                'res_model': 'crm.lead',
                'res_id': lead_id,
                'mimetype': 'application/pdf',
                'type': 'binary',
            }]
        )

        # Post message with attachment in chatter
        odoo.models.execute_kw(
            odoo.DB, odoo.uid, odoo.PASSWORD,
            'crm.lead', 'message_post',
            [[lead_id], {
                'body': f"📎 RFQ Form PDF generated for this lead: <b>{pdf_filename}</b>",
                'attachment_ids': [(4, attachment_id)],
                'message_type': 'comment',
                'subtype_xmlid': 'mail.mt_comment',
            }]
        )
        print(f"✅ PDF uploaded to Odoo chatter for Lead ID {lead_id}")
    except Exception as e:
        print(f"⚠️ Failed to upload PDF to Odoo chatter: {e}")
    # -------------------------------------------------------------------

    return send_file(io.BytesIO(pdf_bytes), download_name=pdf_filename, as_attachment=True)


# ---------------- MAIN ----------------
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True)
