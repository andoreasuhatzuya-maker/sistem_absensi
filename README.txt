SISTEM ABSENSI KARYAWAN - TEMA SILABUS
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
- Antarmuka responsif bergaya lembar silabus
- Relasi pengajuan dan absensi yang konsisten
- Constraint unik dan index database untuk mencegah data ganda

MENJALANKAN DENGAN LARAGON (DIREKOMENDASIKAN)
---------------------------------------------
Project ini adalah aplikasi Python/Flask. Laragon dipakai sebagai lingkungan
Windows dan penyedia Python, sedangkan web server aplikasinya dijalankan oleh
Waitress pada port 5000. Apache dan MySQL Laragon boleh tetap menyala karena
tidak memakai port yang sama.

Persyaratan yang sudah didukung:
- Laragon terpasang di C:\laragon.
- Python tersedia melalui C:\laragon\bin\python\python-*.
- Project boleh berada di C:\sistem_absensi atau dipindahkan ke
  C:\laragon\www\sistem-absensi.

Langkah menjalankan:
1. Buka Laragon.
2. Klik tombol Terminal di Laragon.
3. Masuk ke folder project, contoh:
   cd C:\sistem_absensi
4. Jalankan:
   run-laragon.bat
5. Pada proses pertama, script otomatis:
   - memilih Python bawaan Laragon;
   - membuat virtual environment .venv;
   - memasang library dari requirements.txt;
   - menjalankan aplikasi melalui Waitress.
6. Setelah muncul pesan server aktif, buka:
   http://127.0.0.1:5000
7. Hentikan server dengan Ctrl+C pada Terminal Laragon.

Port dapat diganti sebelum menjalankan script:
   set ABSENSI_PORT=5050
   run-laragon.bat

Kemudian akses http://127.0.0.1:5050.

PENTING:
- Tombol Start All Laragon tidak otomatis menjalankan Flask. Jalankan
  run-laragon.bat setiap kali aplikasi ingin digunakan.
- Jangan menutup Terminal Laragon selama aplikasi sedang dipakai.
- Untuk pemakaian di komputer lain dalam jaringan, ubah konfigurasi listener
  secara sadar dan atur firewall. Konfigurasi bawaan hanya menerima koneksi
  dari komputer ini agar lebih aman.

LOGIN PERTAMA
-------------
Jika database masih baru dan belum mempunyai admin, buka satu kali:
   http://127.0.0.1:5000/buat-admin

Lalu login menggunakan:
   Username: admin
   Password: admin123

Segera ganti password melalui menu Pengaturan.

MENJALANKAN TANPA LARAGON
-------------------------
1. Buka Terminal pada folder project.
2. Buat virtual environment:
   python -m venv .venv
3. Aktifkan:
   .venv\Scripts\activate
4. Install library:
   python -m pip install -r requirements.txt
5. Jalankan server pengembangan:
   python app.py
6. Buka http://127.0.0.1:5000.

CATATAN DATABASE
----------------
Database utama berada di:
instance/database.db

Jika folder instance belum ada, Flask-SQLAlchemy akan membuatnya saat database dibuat.
Jangan menghapus database.db jika ingin mempertahankan data lama.

Saat aplikasi dijalankan, migrasi ringan akan menambahkan index, constraint unik,
dan relasi pengajuan-absensi yang belum tersedia pada instalasi lama. Proses ini
tidak menghapus data. Buat backup berkala lewat menu Pengaturan.

PERUBAHAN PENTING
-----------------
Halaman Absensi sekarang menampilkan SATU TANGGAL, bukan 7 hari x seluruh karyawan.
Jadi 100 karyawan tidak akan menghasilkan 700 baris dalam satu halaman.

Tombol "Tutup Absensi" tidak menghapus data lama. Tombol tersebut hanya membuat record
Tidak Masuk untuk karyawan aktif yang belum memiliki data pada tanggal yang dipilih.

Backup Database menghasilkan file .db yang bisa disimpan sebagai cadangan.
