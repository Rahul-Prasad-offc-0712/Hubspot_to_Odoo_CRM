from flask import Flask, render_template, request, send_file, jsonify
import io, base64, re, requests, os
from odoo_client import OdooClient
import pdfkit  # Render Free works with pip-installed pdfkit

# ---------------- Flask App ----------------
app = Flask(__name__)
odoo = OdooClient()

# ---------------- PDFKit Config (no local path) ----------------
PDFKIT_CONFIG = pdfkit.configuration()  # uses default path, works in Render Free

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

    return odoo.create_lead(lead_data)

# ---------------- Routes ----------------
@app.route("/hubspot_webhook", methods=["POST"])
def hubspot_webhook():
    data = request.json
    values_list = []
    for event in data.get("events", []):
        values_list = event.get("formSubmission", {}).get("values", [])
        if values_list:
            break
    if not values_list and "properties" in data:
        values_list = [{"name": k, "value": v.get("value")} for k, v in data["properties"].items()]
    if not values_list:
        return jsonify({"status": "no data found"}), 400

    filtered_data = parse_values(values_list)
    create_odoo_lead(filtered_data)
    return jsonify({"status": "success"})

# ---------------- RFQ PDF Generation ----------------
@app.route("/submit-rfq", methods=["POST"])
def submit_rfq():
    lead_id = int(request.form.get("lead_id", 0))
    project_name = request.form.get("project_name", "Project")
    safe_project_name = re.sub(r'[^A-Za-z0-9_-]', '_', project_name.strip())

    field_names = request.form.getlist("field_name[]")
    field_values = request.form.getlist("field_value[]")

    pdf_html = f"<html><body><h2>RFQ for {project_name}</h2><table border='1'>"
    pdf_html += "".join([f"<tr><td>{n}</td><td>{v}</td></tr>" for n, v in zip(field_names, field_values)])
    pdf_html += "</table></body></html>"

    try:
        pdf_bytes = pdfkit.from_string(pdf_html, False, configuration=PDFKIT_CONFIG)
    except Exception as e:
        return f"PDF generation failed: {e}", 500

    pdf_filename = f"RFQ_{safe_project_name}_{lead_id}.pdf"
    return send_file(io.BytesIO(pdf_bytes), download_name=pdf_filename, as_attachment=True)

# ---------------- Main ----------------
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))
