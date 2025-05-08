import os
import gspread
from google.oauth2.service_account import Credentials # Lebih modern
# Atau: from oauth2client.service_account import ServiceAccountCredentials # Legacy
from flask import Flask, render_template, request, redirect, url_for, flash
from datetime import datetime

app = Flask(__name__)
app.secret_key = os.environ.get('FLASK_SECRET_KEY', 'jumadi13')

# --- Konfigurasi Google Sheets ---
# Lingkup (scope) izin yang diperlukan
SCOPES = [
    'https://www.googleapis.com/auth/spreadsheets',
    'https://www.googleapis.com/auth/drive.file' # Kadang diperlukan
]

# Path ke file kredensial JSON Anda
# Pastikan file ini ada di direktori yang sama atau atur path dengan benar
SERVICE_ACCOUNT_FILE = 'credentials.json'

# ID Google Sheet tujuan (ambil dari URL sheet)
SPREADSHEET_ID = '1OLpIWJzaTfSNvdvUiEJTLBBnBglBXpj7p--8m_efM-o' # <<< GANTI INI

# --- Fungsi Helper Kalkulasi (Sama seperti sebelumnya, tapi disesuaikan) ---
def calculate_split(people_data, tax_rate_percent, service_rate_percent):
    """Melakukan kalkulasi split bill."""
    summary_data = []
    grand_total_bill = 0.0
    tax_rate = tax_rate_percent / 100.0
    service_rate = service_rate_percent / 100.0

    for person in people_data:
        subtotal_orang = sum(item['price'] for item in person['items'])
        service_charge_orang = subtotal_orang * service_rate
        total_sebelum_pajak_orang = subtotal_orang + service_charge_orang
        pajak_orang = total_sebelum_pajak_orang * tax_rate
        total_akhir_orang = total_sebelum_pajak_orang + pajak_orang
        grand_total_bill += total_akhir_orang

        summary_data.append({
            'nama': person['name'],
            'subtotal': subtotal_orang,
            'service': service_charge_orang,
            'pajak': pajak_orang,
            'total': total_akhir_orang,
            'items_detail': ", ".join([f"{item['name']} (Rp{item['price']:,.2f})" for item in person['items']]) # Tambah detail item
        })

    return summary_data, grand_total_bill

# --- Fungsi untuk Menulis ke Google Sheet ---
def write_to_sheet(spreadsheet_id, sheet_name, data_header, data_rows):
    """Menulis data ke Google Sheet yang ditentukan."""
    try:
        # Otentikasi menggunakan file service account
        creds = Credentials.from_service_account_file(
            SERVICE_ACCOUNT_FILE, scopes=SCOPES
        )
        # Alternatif jika pakai oauth2client:
        # creds = ServiceAccountCredentials.from_json_keyfile_name(
        #     SERVICE_ACCOUNT_FILE, SCOPES
        # )
        client = gspread.authorize(creds)

        # Buka spreadsheet dan worksheet
        spreadsheet = client.open_by_key(spreadsheet_id)

        # Coba buka worksheet, jika tidak ada, buat baru
        try:
            worksheet = spreadsheet.worksheet(sheet_name)
            worksheet.clear() # Hapus data lama (opsional, bisa juga append)
            print(f"Worksheet '{sheet_name}' ditemukan dan dibersihkan.")
        except gspread.WorksheetNotFound:
            worksheet = spreadsheet.add_worksheet(title=sheet_name, rows="100", cols="20")
            print(f"Worksheet '{sheet_name}' tidak ditemukan, worksheet baru dibuat.")

        # Tulis header dan data
        worksheet.update('A1', [data_header]) # Tulis header di baris 1
        worksheet.update(f'A2', data_rows) # Tulis data mulai dari baris 2

        print(f"Data berhasil ditulis ke worksheet '{sheet_name}'.")
        return True, f"https://docs.google.com/spreadsheets/d/{spreadsheet_id}/edit#gid={worksheet.id}"

    except gspread.exceptions.APIError as e:
        print(f"Error Google API: {e}")
        flash(f"Terjadi error saat mengakses Google Sheets: {e}", "error")
        return False, None
    except Exception as e:
        print(f"Terjadi error: {e}")
        flash(f"Terjadi error tidak terduga: {e}", "error")
        return False, None


# --- Rute Flask ---
@app.route('/', methods=['GET'])
def index():
    """Menampilkan halaman form input."""
    # Dapatkan waktu sekarang dan format
    now = datetime.now()
    # Buat nama sheet default dengan format YYYY-MM-DD HH:MM
    default_sheet_name = f"Hasil Split Bill {now.strftime('%Y-%m-%d %H:%M')}"

    # Kirim nama sheet default ke template
    return render_template('index.html', default_sheet_name=default_sheet_name)
# <-- KIRIM VARIABEL

@app.route('/calculate', methods=['POST'])
def calculate_and_save():
    """Menerima data form, kalkulasi, simpan ke GSheet, dan tampilkan hasil."""
    try:
        # Ambil data dasar
        tax_percent = float(request.form.get('tax', 0))
        service_percent = float(request.form.get('service', 0))
        sheet_name = request.form.get('sheet_name', 'Hasil Split Bill') # Nama worksheet

        # Ambil data orang dan item
        # Ini bagian agak tricky karena form bisa dinamis
        # Asumsi sederhana: nama orang dikirim sebagai list request.form.getlist('person_name[]')
        # dan item/harga terkait punya index yang sama
        people_data = []
        person_index = 0
        while True:
            person_name_key = f'person_name_{person_index}'
            if person_name_key not in request.form or not request.form[person_name_key]:
                break # Stop jika nama orang tidak ditemukan/kosong

            person = {'name': request.form[person_name_key], 'items': []}
            item_index = 0
            while True:
                item_name_key = f'item_name_{person_index}_{item_index}'
                item_price_key = f'item_price_{person_index}_{item_index}'

                if item_name_key not in request.form or not request.form[item_name_key]:
                    break # Stop jika nama item kosong

                try:
                    item_price = float(request.form.get(item_price_key, 0))
                    if item_price < 0: item_price = 0 # Harga tidak boleh negatif
                    person['items'].append({
                        'name': request.form[item_name_key],
                        'price': item_price
                    })
                except ValueError:
                    flash(f"Harga item '{request.form.get(item_name_key)}' untuk {person['name']} tidak valid.", "warning")
                    # Bisa lewati item ini atau set harga ke 0
                    person['items'].append({
                        'name': request.form[item_name_key] + " (Harga Error)",
                        'price': 0.0
                    })

                item_index += 1

            if not person['items']: # Jangan proses orang tanpa item
                 flash(f"{person['name']} tidak memiliki item, dilewati.", "warning")
            else:
                 people_data.append(person)
            person_index += 1

        if not people_data:
             flash("Tidak ada data orang yang valid untuk diproses.", "error")
             return redirect(url_for('index'))

        # Lakukan Kalkulasi
        summary_data, grand_total = calculate_split(people_data, tax_percent, service_percent)

        # Siapkan data untuk Google Sheet (hanya ringkasan)
        sheet_header = ["Nama Orang", "Detail Item", "Subtotal (Rp)", "Service (Rp)", "Pajak (Rp)", "Total Akhir (Rp)"]
        sheet_rows = []
        for person in summary_data:
            sheet_rows.append([
                person['nama'],
                person['items_detail'],
                f"{person['subtotal']:,.2f}",
                f"{person['service']:,.2f}",
                f"{person['pajak']:,.2f}",
                f"{person['total']:,.2f}"
            ])
        # Tambahkan baris total
        sheet_rows.append([]) # Baris kosong
        sheet_rows.append(["", "GRAND TOTAL", "", "", "", f"{grand_total:,.2f}"])

        # Tulis ke Google Sheet
        success, sheet_url = write_to_sheet(SPREADSHEET_ID, sheet_name, sheet_header, sheet_rows)

        if success:
            flash(f"Data berhasil dihitung dan disimpan ke Google Sheet!", "success")
            # Tampilkan hasil di halaman web juga
            return render_template('results.html',
                                   summary=summary_data,
                                   grand_total=grand_total,
                                   sheet_url=sheet_url,
                                   sheet_name=sheet_name)
        else:
            # Error sudah di flash di fungsi write_to_sheet
            return redirect(url_for('index')) # Kembali ke form jika gagal simpan

    except Exception as e:
        print(f"Error di route /calculate: {e}")
        flash(f"Terjadi kesalahan saat memproses data: {e}", "error")
        return redirect(url_for('index'))

if __name__ == '__main__':
    # Pastikan path relatif untuk credentials.json benar
    # Atau gunakan path absolut jika perlu
    app.run(debug=True) # debug=True hanya untuk development