from flask import Flask, render_template, request, send_file, jsonify, url_for
import pdfkit, io, base64, requests, json, datetime, os, uuid
from odoo_client import OdooClient

# ---------------- Flask App ----------------
app = Flask(__name__)
odoo = OdooClient()

# ---------------- PDFKit Config ----------------
# Dynamically detect environment (Windows local vs Linux Render)
if os.getenv("RENDER"):
    # Render runs on Linux
    PDFKIT_CONFIG = pdfkit.configuration(wkhtmltopdf="/usr/bin/wkhtmltopdf")
else:
    # Local development (Windows)
    PDFKIT_CONFIG = pdfkit.configuration(
        wkhtmltopdf=r"C:\Program Files\wkhtmltopdf\bin\wkhtmltopdf.exe"
    )

# ---------------- HubSpot → Odoo Lead ----------------
def parse_values(values_list):
    result = {}
    for item in values_list:
        result[item["name"]] = item["value"]
    return result

def create_odoo_lead(values, lead_type="IQL"):
    name = f"{values.get('firstname', '')} {values.get('lastname', '')}".strip() or "Unknown"
    email = values.get("email", "No Email")
    phone = values.get("phone", "")
    city = values.get("city", "")
    lead_data = {
        "name": name,
        "email_from": email,
        "phone": phone,
        "city": city,
        "description": f"Lead from HubSpot ({lead_type})",
    }
    if odoo.search_lead_by_email(email):
        print(f"⚠️ Duplicate lead skipped: {name} ({email})")
        return
    lead_id = odoo.create_lead(lead_data)
    print(f"✅ Lead created: {name} ({email}), Type={lead_type}, ID={lead_id}")
    return lead_id

# ---------------- Routes ----------------
@app.route("/hubspot_webhook", methods=["POST"])
def hubspot_webhook():
    try:
        # Support both JSON and Form submissions
        data = request.get_json(silent=True)
        if not data:
            data = request.form.to_dict()

        print("Received data from HubSpot:", data)

        # Try to extract the list of values
        values_list = []
        if isinstance(data, dict) and "events" in data:
            for event in data.get("events", []):
                values_list = event.get("formSubmission", {}).get("values", [])
                if values_list:
                    break
        elif isinstance(data, dict) and "properties" in data:
            values_list = [{"name": k, "value": v.get("value")} for k, v in data["properties"].items()]
        elif isinstance(data, dict) and data:  # if simple form data
            values_list = [{"name": k, "value": v} for k, v in data.items()]

        if not values_list:
            return jsonify({"status": "no data found", "received": data}), 400

        # Parse and send to Odoo
        parsed = parse_values(values_list)
        create_odoo_lead(parsed, lead_type="IQL")

        return jsonify({"status": "success"}), 200


@app.route("/project/details", methods=["GET"])
def project_details():
    project_name = request.args.get("project_name")
    project_description = request.args.get("project_description")
    project_category = request.args.get("project_category")
    if not project_name or not project_description or not project_category:
        return jsonify({"status": "error", "message": "Missing parameters"}), 400
    domain = [
        ['x_studio_project_name_1', '=', project_name],
        ['x_studio_project_description_1', '=', project_description],
        ['x_studio_project_category_1', '=', project_category]
    ]
    ids = odoo.models.execute_kw(odoo.DB, odoo.uid, odoo.PASSWORD, 'crm.lead', 'search', [domain])
    if not ids:
        return jsonify({"status": "not found"})
    data = odoo.models.execute_kw(
        odoo.DB, odoo.uid, odoo.PASSWORD, 'crm.lead', 'read', [ids[:1]],
        {'fields': ['name', 'x_studio_project_name_1', 'x_studio_project_description_1', 'x_studio_project_category_1']}
    )
    return jsonify({"status": "success", "data": data})

@app.route("/lead/won", methods=["GET"])
def lead_won():
    lead_name = request.args.get("lead_name", "").strip()
    domain = [['stage_id.name', 'ilike', 'won']]
    if lead_name:
        domain.append(['name', 'ilike', lead_name])
    ids = odoo.models.execute_kw(odoo.DB, odoo.uid, odoo.PASSWORD, 'crm.lead', 'search', [domain])
    if ids:
        return jsonify({"status": "success", "message": f"Lead {lead_name or ''} is won successfully"})
    else:
        return jsonify({"status": "not found", "message": "No won lead found"})

# ---------------- RFQ Form ----------------
@app.route("/rfq/<int:lead_id>", methods=["GET"])
def rfq_form(lead_id):
    project_name = request.args.get("project_name", "")
    description = request.args.get("project_description", "")
    category = request.args.get("project_category", "")
    return render_template("rfq_form.html",
                           lead_id=lead_id,
                           project_name=project_name,
                           description=description,
                           category=category)

# ---------------- Submit RFQ ----------------
@app.route("/submit-rfq", methods=["POST"])
def submit_rfq():
    lead_id = int(request.form.get("lead_id", 0))
    if not lead_id:
        return "Invalid lead_id", 400

    # Fetch lead
    lead = odoo.models.execute_kw(
        odoo.DB, odoo.uid, odoo.PASSWORD, 'crm.lead', 'read', [[lead_id]],
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

    pdf_html = f"""<html><head><style>
        body {{ font-family: 'Times New Roman', serif; font-size: 14px; line-height: 1.5; margin: 40px; }}
        table {{ width:100%; border-collapse: collapse; margin-top: 10px; }}
        th, td {{ border: 1px solid #ccc; padding: 8px; text-align: left; }}
        th {{ background: #f4f4f4; }}
        .header-table td {{ border:none; vertical-align: top; }}
        </style></head>
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
        </body></html>"""

    pdf_bytes = pdfkit.from_string(pdf_html, False, configuration=PDFKIT_CONFIG)

    # Upload PDF to Odoo as attachment
    pdf_base64 = base64.b64encode(pdf_bytes).decode('utf-8')
    attachment_vals = {
        "name": f"RFQ_{quotation_number}.pdf",
        "datas": pdf_base64,
        "res_model": "crm.lead",
        "res_id": lead_id,
        "type": "binary",
        "mimetype": "application/pdf",
    }
    attachment_id = odoo.models.execute_kw(
        odoo.DB, odoo.uid, odoo.PASSWORD,
        "ir.attachment", "create", [attachment_vals]
    )
    print(f"✅ Uploaded PDF as attachment ID: {attachment_id} in Odoo for lead {lead_id}")

    return send_file(io.BytesIO(pdf_bytes), download_name=f"RFQ_{quotation_number}.pdf", as_attachment=True)

# ---------------- MAIN ----------------
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True)
