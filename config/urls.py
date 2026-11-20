from django.contrib import admin
from django.urls import path
from django.conf import settings
from django.conf.urls.static import static
from laporan import views

urlpatterns = [
    path('admin/', admin.site.urls),

    # Autentikasi: Login & Logout
    path('login/', views.login_view, name='login'),
    path('logout/', views.logout_view, name='logout'),
    path('profil/', views.profil_view, name='profil'),
    path('backup/', views.backup_data, name='backup_data'),
    path('laporan/<int:laporan_id>/export-csv/', views.laporan_export_csv, name='laporan_export_csv'),

    # Dashboard
    path('', views.dashboard, name='dashboard'),

    # Laporan Bulanan
    path('laporan/<int:pk>/', views.laporan_detail, name='laporan_detail'),
    path('laporan/<int:pk>/edit/', views.laporan_edit, name='laporan_edit'),
    path('laporan/<int:pk>/hapus/', views.laporan_hapus, name='laporan_hapus'),
    path('laporan/<int:pk>/status/', views.laporan_status, name='laporan_status'),
    path('laporan/<int:laporan_id>/generate-word/', views.generate_word, name='generate_word'),

    # Pengaturan Dinamis Lengkap (Teks Berwarna Draft: Seksi, Pejabat, Klasifikasi Anggaran)
    path('laporan/<int:laporan_id>/pengaturan/simpan/', views.laporan_pengaturan_simpan, name='laporan_pengaturan_simpan'),
    path('laporan/<int:laporan_id>/preset/<str:preset_type>/', views.laporan_terapkan_preset, name='laporan_terapkan_preset'),
    path('laporan/<int:laporan_id>/pegawai/<int:pegawai_id>/nomor-dokumen/', views.nomor_dokumen_pegawai_simpan, name='nomor_dokumen_pegawai_simpan'),

    # Tanda Tangan Digital (Upload File & Gambar Langsung)
    path('ttd/<str:nama_berkas>', views.tanda_tangan_gambar, name='tanda_tangan_gambar'),
    path('laporan/<int:laporan_id>/tanda-tangan/simpan/', views.tanda_tangan_simpan, name='tanda_tangan_simpan'),
    path('laporan/<int:laporan_id>/tanda-tangan/hapus/', views.tanda_tangan_hapus, name='tanda_tangan_hapus'),

    # Pekerjaan & SPK
    path('laporan/<int:laporan_id>/pekerjaan/simpan/', views.pekerjaan_simpan, name='pekerjaan_simpan'),
    path('pekerjaan/<int:pk>/hapus/', views.pekerjaan_hapus, name='pekerjaan_hapus'),

    # Pembayaran Pegawai
    path('laporan/<int:laporan_id>/pembayaran/simpan/', views.pembayaran_simpan, name='pembayaran_simpan'),
    path('laporan/<int:laporan_id>/pembayaran/tambah-semua/', views.pembayaran_tambah_semua, name='pembayaran_tambah_semua'),
    path('pembayaran/<int:pk>/hapus/', views.pembayaran_hapus, name='pembayaran_hapus'),

    # Nomor Dokumen
    path('laporan/<int:laporan_id>/nomor-dokumen/simpan/', views.nomor_dokumen_simpan, name='nomor_dokumen_simpan'),

    # Master Pegawai
    path('pegawai/', views.pegawai_list, name='pegawai_list'),
    path('pegawai/tambah/', views.pegawai_tambah, name='pegawai_tambah'),
    path('pegawai/<int:pk>/edit/', views.pegawai_edit, name='pegawai_edit'),
    path('pegawai/<int:pk>/hapus/', views.pegawai_hapus, name='pegawai_hapus'),

    # Seeder Contoh Kedinasan (Pengujian & Impor Awal)
    path('seed-contoh/', views.seed_contoh_data, name='seed_contoh_data'),
]

# Dukungan media files (Tanda Tangan Digital, Gambar)
if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
