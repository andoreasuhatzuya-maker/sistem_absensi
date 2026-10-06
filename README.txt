SISTEM ABSENSI KARYAWAN - VERSI RAPi
====================================

Fitur utama:
- Login admin
- Dashboard ringkas
- Data karyawan aktif/nonaktif
- Absensi harian berdasarkan tanggal
- Penutupan absensi: yang belum diinput menjadi Tidak Masuk
- Data Sakit/Izin + upload bukti
- Lembur per karyawan
- Laporan periode + PDF
- Backup database .db
- Pengaturan + ganti password admin

CARA MENJALANKAN DI WINDOWS
---------------------------
1. Buka folder project di VS Code.
2. Pastikan Python terpasang.
3. Buka Terminal.
4. Buat virtual environment jika belum ada:
   python -m venv venv
5. Aktifkan:
   venv\Scripts\activate
6. Install library:
   pip install -r requirements.txt
7. Jalankan:
   python app.py
8. Buka browser:
   http://127.0.0.1:5000
9. Jika belum ada admin, buka sekali:
   http://127.0.0.1:5000/buat-admin
10. Login:
   Username: admin
   Password: admin123

CATATAN DATABASE
----------------
Database utama berada di:
instance/database.db

Jika folder instance belum ada, Flask-SQLAlchemy akan membuatnya saat database dibuat.
Jangan menghapus database.db jika ingin mempertahankan data lama.

PERUBAHAN PENTING
-----------------
Halaman Absensi sekarang menampilkan SATU TANGGAL, bukan 7 hari x seluruh karyawan.
Jadi 100 karyawan tidak akan menghasilkan 700 baris dalam satu halaman.

Tombol "Tutup Absensi" tidak menghapus data lama. Tombol tersebut hanya membuat record
Tidak Masuk untuk karyawan aktif yang belum memiliki data pada tanggal yang dipilih.

Backup Database menghasilkan file .db yang bisa disimpan sebagai cadangan.
