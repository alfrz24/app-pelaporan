from django.shortcuts import render, redirect, get_object_or_404
from django.contrib import messages
from django.contrib.auth import authenticate, login, logout, update_session_auth_hash
from django.contrib.auth.forms import PasswordChangeForm
import csv
import json
from django.contrib.auth.decorators import login_required
from django.contrib.auth.models import User
from django.http import HttpResponse, Http404, JsonResponse
from django.utils import timezone
from django.conf import settings
from decimal import Decimal
import datetime
import os
import re
import base64

from .models import (
    LaporanBulanan,
    Pegawai,
    Pekerjaan,
    Pembayaran,
    NomorDokumen,
    Pemeriksaan,
    Penugasan,
    StokBulanan,
)
from . import signatures as ttd_store
from .word_generator import (
    generate_exact_word_docx,
    generate_all_pegawai_zip,
    NAMA_BULAN,
    BULAN_ROMAWI,
    format_rupiah_standard,
    terbilang
)


# =====================================================
# 0. AUTENTIKASI: LOGIN & LOGOUT
# =====================================================

def login_view(request):
    """
    Halaman Login Pengguna Berbasis Password.
    Otomatis membuat akun admin default jika belum ada user di database.
    """
    # Pastikan user default ada jika database baru/kosong
    try:
        if not User.objects.filter(is_superuser=True).exists():
            User.objects.create_superuser(
                username='admin',
                email='admin@kominfotik.go.id',
                password='admin'
            )
    except Exception:
        pass

    if request.user.is_authenticated:
        return redirect('dashboard')

    if request.method == 'POST':
        username = request.POST.get('username', '').strip()
        password = request.POST.get('password', '').strip()

        if not username or not password:
            messages.error(request, 'Username dan password wajib diisi.')
            return render(request, 'auth/login.html')

        user = authenticate(request, username=username, password=password)
        if user is not None:
            login(request, user)
            messages.success(request, f'Selamat datang kembali, {user.first_name or user.username}!')
            next_url = request.GET.get('next') or request.POST.get('next') or 'dashboard'
            return redirect(next_url)
        else:
            messages.error(request, 'Username atau password yang Anda masukkan salah. Silakan coba lagi.')

    return render(request, 'auth/login.html')


def logout_view(request):
    """Logout pengguna dan alihkan ke halaman login"""
    logout(request)
    messages.info(request, 'Anda telah berhasil keluar (logout) dari sistem.')
    return redirect('login')


# =====================================================
# 1. DASHBOARD
# =====================================================

@login_required(login_url='login')
def dashboard(request):
    if request.method == 'POST':
        bulan = request.POST.get('bulan')
        tahun = request.POST.get('tahun')
        tanggal_mulai = request.POST.get('tanggal_mulai') or None
        tanggal_selesai = request.POST.get('tanggal_selesai') or None
        status = request.POST.get('status', 'draft')

        if not bulan or not tahun:
            messages.error(request, 'Bulan dan tahun wajib diisi.')
            return redirect('dashboard')

        # Satu bulan boleh memiliki banyak laporan (mis. satu laporan per pegawai).
        laporan = LaporanBulanan.objects.create(
            bulan=int(bulan),
            tahun=int(tahun),
            tanggal_mulai=tanggal_mulai,
            tanggal_selesai=tanggal_selesai,
            status=status,
            created_at=timezone.now()
        )

        # Salin pengaturan (template, nomor surat, pejabat, SPK) dari laporan lain
        salin_dari = request.POST.get('salin_dari')
        sumber = LaporanBulanan.objects.filter(pk=salin_dari).first() if salin_dari else None
        if sumber:
            salin_pengaturan_laporan(sumber, laporan)

        # Pegawai untuk laporan ini
        pegawai = Pegawai.objects.filter(pk=request.POST.get('pegawai_id')).first() if request.POST.get('pegawai_id') else None
        if pegawai:
            buat_pembayaran_default(laporan, pegawai, sumber)

        judul = request.POST.get('judul_laporan', '').strip() or (f'Laporan {pegawai.nama}' if pegawai else '')
        if judul:
            NomorDokumen.objects.create(laporan=laporan, jenis_dokumen='judul_laporan', nomor_surat=judul[:150])

        extra = f' untuk {pegawai.nama}' if pegawai else ''
        messages.success(request, f'Laporan {NAMA_BULAN.get(int(bulan), bulan)} {tahun}{extra} berhasil dibuat.')
        return redirect('laporan_detail', pk=laporan.pk)

    laporan_list = list(LaporanBulanan.objects.all().order_by('-tahun', '-bulan', '-id'))
    pekerjaan_list = Pekerjaan.objects.all().order_by('-id')[:5]

    # Judul & nama pegawai tiap laporan (untuk daftar)
    judul_map = {nd.laporan_id: nd.nomor_surat for nd in NomorDokumen.objects.filter(jenis_dokumen='judul_laporan')}
    pegawai_map = {}
    for pb in Pembayaran.objects.select_related('pegawai'):
        pegawai_map.setdefault(pb.laporan_id, []).append(pb.pegawai.nama)
    for item in laporan_list:
        item.judul = judul_map.get(item.id, '')
        names = pegawai_map.get(item.id, [])
        item.pegawai_ringkas = (', '.join(names[:2]) + (f' +{len(names) - 2} lainnya' if len(names) > 2 else '')) if names else ''

    total_laporan = len(laporan_list)
    total_pegawai = Pegawai.objects.count()

    # Filter & pencarian daftar laporan
    q = request.GET.get('q', '').strip()
    f_tahun = request.GET.get('tahun', '').strip()
    f_status = request.GET.get('status', '').strip()
    laporan_tampil = []
    for item in laporan_list:
        if f_tahun and str(item.tahun) != f_tahun:
            continue
        if f_status and item.status != f_status:
            continue
        if q:
            hay = f"{item.judul} {item.pegawai_ringkas} {NAMA_BULAN.get(item.bulan, '')} {item.bulan}/{item.tahun}".lower()
            if q.lower() not in hay:
                continue
        laporan_tampil.append(item)

    # Data grafik: total diterima per periode (12 periode terakhir) & komposisi status
    per_periode = {}
    for pb in Pembayaran.objects.select_related('laporan'):
        key = (pb.laporan.tahun, pb.laporan.bulan)
        per_periode[key] = per_periode.get(key, Decimal(0)) + (pb.total_diterima or pb.honorarium or Decimal(0))
    keys = sorted(per_periode)[-12:]
    chart_labels = [f"{NAMA_BULAN.get(b, b)[:3]} {t}" for t, b in keys]
    chart_values = [int(per_periode[k]) for k in keys]
    n_selesai = sum(1 for i in laporan_list if i.status == 'selesai')
    chart_status = [n_selesai, total_laporan - n_selesai]
    persen_selesai = int((n_selesai / total_laporan * 100)) if total_laporan > 0 else 100
    laporan_terbaru = laporan_list[:3]

    # Hitung total honor keseluruhan dari seluruh pembayaran
    total_honor_all = Decimal(0)
    for pb in Pembayaran.objects.all():
        total_honor_all += (pb.total_diterima or pb.honorarium or Decimal(0))

    context = {
        'laporan_list': laporan_list,
        'laporan_tampil': laporan_tampil,
        'laporan_terbaru': laporan_terbaru,
        'persen_selesai': persen_selesai,
        'filter_q': q, 'filter_tahun': f_tahun, 'filter_status': f_status,
        'daftar_tahun': sorted({i.tahun for i in laporan_list}, reverse=True),
        'chart_json': json.dumps({'labels': chart_labels, 'values': chart_values, 'status': chart_status}),
        'total_selesai': n_selesai,
        'total_draft': total_laporan - n_selesai,
        'pekerjaan_list': pekerjaan_list,
        'total_laporan': total_laporan,
        'total_pegawai': total_pegawai,
        'total_honor_all': total_honor_all,
        'all_pegawai': Pegawai.objects.all().order_by('nama'),
    }
    return render(request, 'dashboard.html', context)


@login_required(login_url='login')
def laporan_export_csv(request, laporan_id):
    """Ekspor rekap pembayaran satu laporan ke CSV (dapat dibuka di Excel)."""
    laporan = get_object_or_404(LaporanBulanan, pk=laporan_id)
    resp = HttpResponse(content_type='text/csv; charset=utf-8')
    resp['Content-Disposition'] = (
        f'attachment; filename="Rekap_{NAMA_BULAN.get(laporan.bulan, laporan.bulan)}_{laporan.tahun}_LP{laporan.id}.csv"')
    resp.write('\ufeff')
    w = csv.writer(resp, delimiter=';')
    w.writerow(['No', 'ID PHL', 'Nama', 'Jabatan', 'No Rekening', 'NPWP', 'Honorarium', 'Potongan Absen',
                'BPJS 1%', 'PPh 21', 'BPJS 4%', 'BPJS Ketenagakerjaan', 'Nilai Bruto', 'Total Diterima'])
    for i, pb in enumerate(Pembayaran.objects.filter(laporan=laporan).select_related('pegawai').order_by('id'), 1):
        p = pb.pegawai
        w.writerow([i, p.id_phl or '', p.nama, p.jabatan or '', p.nomor_rekening or '', p.npwp or '',
                    int(pb.honorarium or 0), int(pb.potongan_kehadiran or 0), int(pb.bpjs or 0),
                    int(pb.pph21 or 0), int(pb.bpjs_pemberi_kerja or 0), int(pb.bpjs_ketenagakerjaan or 0),
                    int(pb.nilai_bruto or 0), int(pb.total_diterima or 0)])
    return resp


@login_required(login_url='login')
def backup_data(request):
    """Unduh cadangan seluruh data aplikasi (JSON) - hanya untuk administrator."""
    if not request.user.is_superuser:
        messages.error(request, 'Hanya administrator yang dapat mengunduh cadangan.')
        return redirect('profil')
    from django.core.management import call_command
    import io as _io
    buf = _io.StringIO()
    call_command('dumpdata', 'laporan', indent=2, stdout=buf)
    resp = HttpResponse(buf.getvalue(), content_type='application/json; charset=utf-8')
    resp['Content-Disposition'] = f'attachment; filename="backup_pelaporan_{timezone.localtime():%Y%m%d_%H%M}.json"'
    return resp


@login_required(login_url='login')
def profil_view(request):
    """Profil pengguna: ubah nama tampilan & ganti password."""
    form = PasswordChangeForm(request.user)
    if request.method == 'POST':
        if request.POST.get('aksi') == 'profil':
            request.user.first_name = request.POST.get('first_name', '').strip()[:150]
            request.user.email = request.POST.get('email', '').strip()[:254]
            request.user.save()
            messages.success(request, 'Profil berhasil diperbarui.')
            return redirect('profil')
        form = PasswordChangeForm(request.user, request.POST)
        if form.is_valid():
            user = form.save()
            update_session_auth_hash(request, user)
            messages.success(request, 'Password berhasil diganti.')
            return redirect('profil')
        messages.error(request, 'Password gagal diganti. Periksa isian Anda.')
    return render(request, 'auth/profil.html', {'form': form})


def salin_pengaturan_laporan(sumber, tujuan):
    """Salin pengaturan global (template seksi, pejabat, SPK, nomor surat) + data pekerjaan.
    Nomor surat khusus per-pegawai (berakhiran _<id>) dan judul tidak ikut disalin."""
    for nd in NomorDokumen.objects.filter(laporan=sumber):
        if nd.jenis_dokumen == 'judul_laporan' or re.search(r'_\d+$', nd.jenis_dokumen):
            continue
        NomorDokumen.objects.create(
            laporan=tujuan, jenis_dokumen=nd.jenis_dokumen,
            nomor_surat=nd.nomor_surat, tanggal_surat=nd.tanggal_surat)
    for pk_ in Pekerjaan.objects.filter(laporan=sumber):
        Pekerjaan.objects.create(
            laporan=tujuan, nama_pekerjaan=pk_.nama_pekerjaan, nomor_spk=pk_.nomor_spk,
            tanggal_spk=pk_.tanggal_spk, volume=pk_.volume, keterangan=pk_.keterangan)


def buat_pembayaran_default(laporan, pegawai, sumber=None):
    """Buat data pembayaran pegawai; nilai disalin dari pembayaran terakhir pegawai
    tersebut (atau dari laporan sumber), bila tidak ada dihitung dari honor standar."""
    ref = None
    if sumber:
        ref = Pembayaran.objects.filter(laporan=sumber, pegawai=pegawai).first()
    if not ref:
        ref = Pembayaran.objects.filter(pegawai=pegawai).order_by('-id').first()
    if ref:
        honor = ref.honorarium or Decimal(0)
        pot = Decimal(0)
        bpjs1 = ref.bpjs if ref.bpjs is not None else (honor * Decimal('0.01')).quantize(Decimal('1'))
        bpjs4 = ref.bpjs_pemberi_kerja if ref.bpjs_pemberi_kerja is not None else (honor * Decimal('0.04')).quantize(Decimal('1'))
        pph = ref.pph21 or Decimal(0)
        naker = ref.bpjs_ketenagakerjaan or Decimal(0)
    else:
        honor = Decimal(7100000)
        pot = Decimal(0)
        bpjs1 = (honor * Decimal('0.01')).quantize(Decimal('1'))
        bpjs4 = (honor * Decimal('0.04')).quantize(Decimal('1'))
        pph = Decimal(0)
        naker = (honor * Decimal('0.0054')).quantize(Decimal('1'))
    return Pembayaran.objects.create(
        laporan=laporan, pegawai=pegawai, honorarium=honor,
        potongan_kehadiran=pot, jumlah_setelah_potongan_absen=honor - pot,
        bpjs=bpjs1, pph21=pph, bpjs_pemberi_kerja=bpjs4,
        nilai_bruto=honor + bpjs4, bpjs_ketenagakerjaan=naker,
        total_diterima=max(honor - pot - bpjs1 - pph, Decimal(0)))


# =====================================================
# 2. DETAIL & KELOLA LAPORAN BULANAN
# =====================================================

@login_required(login_url='login')
def laporan_detail(request, pk):
    laporan = get_object_or_404(LaporanBulanan, pk=pk)
    
    pekerjaan_list = Pekerjaan.objects.filter(laporan=laporan).order_by('id')
    pembayaran_list = Pembayaran.objects.filter(laporan=laporan).select_related('pegawai').order_by('id')
    nomor_dokumen_list = NomorDokumen.objects.filter(laporan=laporan)
    all_pegawai = Pegawai.objects.all().order_by('nama')

    # Mapping nomor dokumen dan pengaturan agar mudah diakses di template
    doc_numbers = {}
    for nd in nomor_dokumen_list:
        doc_numbers[nd.jenis_dokumen] = nd.nomor_surat

    bulan_int = laporan.bulan
    tahun_int = laporan.tahun
    bulan_nama = NAMA_BULAN.get(bulan_int, 'Oktober')
    romawi = BULAN_ROMAWI.get(bulan_int, 'X')
    bulan_berikut_idx = (bulan_int % 12) + 1
    bulan_berikut_nama = NAMA_BULAN.get(bulan_berikut_idx, 'November')

    # Default presets jika belum pernah disimpan di DB
    defaults = {
        'nama_seksi': 'Seksi Aplikasi, Siber dan Statistik',
        'kode_seksi': 'ASTIK',
        'pptk_nama': 'Yuli Yanti',
        'pptk_nip': '197107251998032004',
        'pptk_jabatan': 'Kepala Seksi Aplikasi, Siber dan Statistik Suku Dinas Komunikasi, Informatika, dan Statistik Kota Administrasi Jakarta Pusat',
        'program': 'Program Penyelenggaraan Persandian Untuk Pengamanan Informasi',
        'kegiatan': 'Penyelenggaraan Persandian untuk Pengamanan Informasi Pemerintah Daerah Provinsi',
        'sub_kegiatan': 'Penyediaan Layanan Keamanan Informasi dan Persandian Pemerintah Daerah',
        'aktivitas': 'PJLP Layanan Keamanan Informasi',
        'kode_rekening': '5.1.02.02.001.00039 Belanja Jasa Tenaga Informasi dan Teknologi',
        'nama_pekerjaan': 'Petugas Informasi dan Teknologi-Aplication Support Kominfotik Technical Support',
        'volume': '1 BOK',
        'nomor_spk': '01/PN.01.02',
        'tanggal_spk': '2 Januari 2026',
        'tahun_anggaran': str(tahun_int),
        'permintaan_pemeriksaan': f"152/0006.0001/ASTIK/PJLP.KI/{romawi}/{tahun_int}",
        'permintaan_teknis': "1439/PN.01.02",
        'undangan': f"19/TPPBJ/KMFJP/ASTIK/0006.0001/{romawi}/{tahun_int}",
        'berita_acara_pemeriksaan': f"20/TPPBJ/KMFJP/ASTIK/PJLP.KI/{romawi}/{tahun_int}",
        'bast': "1440/PN.01.02",
        'bapp': "1441/PN.01.02",
        'kwitansi': f"88/KWT/ASTIK/0006.0001/XI/{tahun_int}",
        'tanggal_surat': f"30 {bulan_nama} {tahun_int}",
        'tanggal_kwitansi': f"02 {bulan_berikut_nama} {tahun_int}",
        'hari_pembuatan': 'Jumat',
        'penyebutan_tanggal': 'Tiga Puluh',
        'waktu_pemeriksaan': '16.30 s.d Selesai',
        'tempat_pemeriksaan': 'Sudin Kominfotik Kota Administrasi Jakarta Pusat',
        'ppk_nama': 'Rachmat Setiawan',
        'ppk_nip': '198102022006041009',
        'bendahara_nama': 'Roslaini Harahap',
        'bendahara_nip': '197203121993032007',
        'tppbj_ketua': 'Eka Novia Gunawan',
        'tppbj_ketua_nip': '198011082011011007',
        'tppbj_sekretaris': 'Reza Ayatuna Lazuardy',
        'tppbj_anggota': 'Sulaeman',
        'sk_tppbj': f"03 Tahun {tahun_int}",
    }

    # Isi default ke doc_numbers jika key belum ada
    for k, v in defaults.items():
        if k not in doc_numbers:
            doc_numbers[k] = v

    # Hitung total pembayaran
    total_honor = Decimal(0)
    total_potongan = Decimal(0)
    total_setelah_pot = Decimal(0)
    total_bpjs1 = Decimal(0)
    total_pph21 = Decimal(0)
    total_diterima = Decimal(0)
    total_bpjs4 = Decimal(0)
    total_bruto = Decimal(0)
    total_bpjs_naker = Decimal(0)

    # Cek ketersediaan tanda tangan (disimpan di database)
    ttd_ada = ttd_store.daftar_ada()
    pembayaran_with_sig = []
    for p in pembayaran_list:
        h = p.honorarium or Decimal(0)
        pot = p.potongan_kehadiran or Decimal(0)
        set_pot = p.jumlah_setelah_potongan_absen or (h - pot)
        b1 = p.bpjs or Decimal(0)
        pph = p.pph21 or Decimal(0)
        terima = p.total_diterima or (set_pot - b1 - pph)
        b4 = p.bpjs_pemberi_kerja or Decimal(0)
        bruto = p.nilai_bruto or (h + b4)
        bnaker = p.bpjs_ketenagakerjaan or Decimal(0)

        total_honor += h
        total_potongan += pot
        total_setelah_pot += set_pot
        total_bpjs1 += b1
        total_pph21 += pph
        total_diterima += terima
        total_bpjs4 += b4
        total_bruto += bruto
        total_bpjs_naker += bnaker

        # Cek apakah tanda tangan pegawai ini sudah diunggah/digambar
        sig_file = f"pegawai_{p.pegawai.id}.png"
        has_sig = sig_file in ttd_ada
        p.has_signature = has_sig
        p.signature_filename = sig_file if has_sig else None
        pembayaran_with_sig.append(p)

    # Cek tanda tangan pejabat
    has_sig_pptk = 'pejabat_pptk.png' in ttd_ada
    has_sig_ppk = 'pejabat_ppk.png' in ttd_ada
    has_sig_bendahara = 'pejabat_bendahara.png' in ttd_ada

    terbilang_total = terbilang(total_diterima)

    # Checklist kelengkapan berkas (berdasarkan data yang benar-benar tersimpan)
    tersimpan = {nd.jenis_dokumen: (nd.nomor_surat or '').strip() for nd in nomor_dokumen_list}
    kunci_nomor = ['permintaan_pemeriksaan', 'permintaan_teknis', 'undangan',
                   'berita_acara_pemeriksaan', 'bast', 'bapp', 'kwitansi']
    n_ttd = sum(1 for p in pembayaran_with_sig if p.has_signature)
    n_peg = len(pembayaran_with_sig)
    checklist = [
        {'label': 'Pegawai & pembayaran terisi', 'ok': n_peg > 0, 'tab': 'pembayaran-pane',
         'info': f'{n_peg} pegawai'},
        {'label': 'Template seksi & pejabat disimpan', 'ok': bool(tersimpan.get('nama_seksi') and tersimpan.get('pptk_nama')),
         'tab': 'pejabat-pane', 'info': 'Tab Seksi & Pejabat'},
        {'label': 'Klasifikasi anggaran & SPK disimpan', 'ok': bool(tersimpan.get('program') and tersimpan.get('nomor_spk')),
         'tab': 'pekerjaan-pane', 'info': 'Tab Klasifikasi & SPK'},
        {'label': 'Seluruh nomor surat terisi', 'ok': all(tersimpan.get(k) for k in kunci_nomor),
         'tab': 'dokumen-pane', 'info': f"{sum(1 for k in kunci_nomor if tersimpan.get(k))}/{len(kunci_nomor)} nomor"},
        {'label': 'Tanggal surat & kwitansi terisi', 'ok': bool(tersimpan.get('tanggal_surat') and tersimpan.get('tanggal_kwitansi')),
         'tab': 'dokumen-pane', 'info': 'Tab Nomor Surat'},
        {'label': 'Tanda tangan digital (opsional)', 'ok': n_peg > 0 and n_ttd == n_peg, 'opsional': True,
         'tab': 'ttd-pane', 'info': f'{n_ttd}/{n_peg} pegawai'},
    ]
    wajib = [c for c in checklist if not c.get('opsional')]
    progress = int(100 * sum(1 for c in wajib if c['ok']) / len(wajib))

    # Nomor surat khusus per pegawai (untuk mengisi otomatis form "Nomor Surat Khusus")
    pegawai_nomor = {}
    for k, v in tersimpan.items():
        m = re.match(r'^(no_jkd|no_tu1|no_tu2|no_tu3|no_tppbj1|no_tppbj2|no_kwt|spk)_(\d+)$', k)
        if m:
            pegawai_nomor.setdefault(m.group(2), {})[m.group(1)] = v

    context = {
        'laporan': laporan,
        'bulan_nama': bulan_nama,
        'pekerjaan_list': pekerjaan_list,
        'pembayaran_list': pembayaran_with_sig,
        'nomor_dokumen_list': nomor_dokumen_list,
        'doc_numbers': doc_numbers,
        'all_pegawai': all_pegawai,
        'total_honor': total_honor,
        'total_potongan': total_potongan,
        'total_setelah_pot': total_setelah_pot,
        'total_bpjs1': total_bpjs1,
        'total_pph21': total_pph21,
        'total_diterima': total_diterima,
        'total_bpjs4': total_bpjs4,
        'total_bruto': total_bruto,
        'total_bpjs_naker': total_bpjs_naker,
        'terbilang_total': terbilang_total,
        'has_sig_pptk': has_sig_pptk,
        'has_sig_ppk': has_sig_ppk,
        'has_sig_bendahara': has_sig_bendahara,
        'checklist': checklist,
        'progress': progress,
        'pegawai_nomor_json': json.dumps(pegawai_nomor),
    }
    return render(request, 'laporan/detail.html', context)


@login_required(login_url='login')
def laporan_edit(request, pk):
    laporan = get_object_or_404(LaporanBulanan, pk=pk)

    if request.method == 'POST':
        bulan = request.POST.get('bulan')
        tahun = request.POST.get('tahun')
        tanggal_mulai = request.POST.get('tanggal_mulai') or None
        tanggal_selesai = request.POST.get('tanggal_selesai') or None
        status = request.POST.get('status', 'draft')

        if not bulan or not tahun:
            messages.error(request, 'Bulan dan tahun wajib diisi.')
            return render(request, 'laporan/form.html', {'laporan': laporan})

        laporan.bulan = int(bulan)
        laporan.tahun = int(tahun)
        laporan.tanggal_mulai = tanggal_mulai
        laporan.tanggal_selesai = tanggal_selesai
        laporan.status = status
        laporan.save()

        messages.success(request, f'Laporan periode {NAMA_BULAN.get(int(bulan), bulan)} {tahun} berhasil diperbarui.')
        return redirect('laporan_detail', pk=laporan.pk)

    return render(request, 'laporan/form.html', {'laporan': laporan})


@login_required(login_url='login')
def laporan_hapus(request, pk):
    laporan = get_object_or_404(LaporanBulanan, pk=pk)

    if request.method == 'POST':
        # Hapus data berelasi
        NomorDokumen.objects.filter(laporan=laporan).delete()
        Pembayaran.objects.filter(laporan=laporan).delete()
        Penugasan.objects.filter(laporan=laporan).delete()
        StokBulanan.objects.filter(laporan=laporan).delete()
        Pekerjaan.objects.filter(laporan=laporan).delete()
        
        bulan_nama = NAMA_BULAN.get(laporan.bulan, laporan.bulan)
        tahun = laporan.tahun
        laporan.delete()

        messages.success(request, f'Laporan periode {bulan_nama} {tahun} berhasil dihapus.')
        return redirect('dashboard')

    return render(request, 'laporan/konfirmasi_hapus.html', {'laporan': laporan})


@login_required(login_url='login')
def laporan_status(request, pk):
    laporan = get_object_or_404(LaporanBulanan, pk=pk)
    if request.method == 'POST':
        if laporan.status == 'draft':
            laporan.status = 'selesai'
            messages.success(request, 'Status laporan berhasil diubah menjadi Selesai.')
        else:
            laporan.status = 'draft'
            messages.info(request, 'Status laporan dikembalikan menjadi Draft.')
        laporan.save()
    return redirect('laporan_detail', pk=laporan.pk)


# =====================================================
# 3. KELOLA PEKERJAAN & SPK
# =====================================================

@login_required(login_url='login')
def pekerjaan_simpan(request, laporan_id):
    laporan = get_object_or_404(LaporanBulanan, pk=laporan_id)

    if request.method == 'POST':
        pekerjaan_id = request.POST.get('pekerjaan_id')
        nama_pekerjaan = request.POST.get('nama_pekerjaan', '').strip()
        nomor_spk = request.POST.get('nomor_spk', '').strip()
        tanggal_spk = request.POST.get('tanggal_spk') or None
        volume = request.POST.get('volume', '').strip()
        keterangan = request.POST.get('keterangan', '').strip()

        if not nama_pekerjaan:
            messages.error(request, 'Nama pekerjaan wajib diisi.')
            return redirect('laporan_detail', pk=laporan.pk)

        if pekerjaan_id:
            pekerjaan = get_object_or_404(Pekerjaan, pk=pekerjaan_id, laporan=laporan)
            pekerjaan.nama_pekerjaan = nama_pekerjaan
            pekerjaan.nomor_spk = nomor_spk
            pekerjaan.tanggal_spk = tanggal_spk
            pekerjaan.volume = volume
            pekerjaan.keterangan = keterangan
            pekerjaan.save()
            messages.success(request, 'Data pekerjaan / SPK berhasil diperbarui.')
        else:
            Pekerjaan.objects.create(
                laporan=laporan,
                nama_pekerjaan=nama_pekerjaan,
                nomor_spk=nomor_spk,
                tanggal_spk=tanggal_spk,
                volume=volume,
                keterangan=keterangan
            )
            messages.success(request, 'Pekerjaan / SPK baru berhasil ditambahkan.')

    return redirect('laporan_detail', pk=laporan.pk)


@login_required(login_url='login')
def pekerjaan_hapus(request, pk):
    pekerjaan = get_object_or_404(Pekerjaan, pk=pk)
    laporan_id = pekerjaan.laporan_id
    if request.method == 'POST':
        pekerjaan.delete()
        messages.success(request, 'Pekerjaan berhasil dihapus.')
    return redirect('laporan_detail', pk=laporan_id)


# =====================================================
# 4. KELOLA DATA PEMBAYARAN PEGAWAI
# =====================================================

@login_required(login_url='login')
def pembayaran_simpan(request, laporan_id):
    laporan = get_object_or_404(LaporanBulanan, pk=laporan_id)

    if request.method == 'POST':
        pembayaran_id = request.POST.get('pembayaran_id')
        pegawai_id = request.POST.get('pegawai_id')

        try:
            honorarium = Decimal(str(request.POST.get('honorarium') or 0))
            potongan_kehadiran = Decimal(str(request.POST.get('potongan_kehadiran') or 0))
            
            # Rumus 1: Jumlah setelah potongan absen
            jumlah_setelah_potongan_absen = honorarium - potongan_kehadiran
            if jumlah_setelah_potongan_absen < 0:
                jumlah_setelah_potongan_absen = Decimal(0)

            # Rumus 2: BPJS 1% (karyawan)
            bpjs_input = request.POST.get('bpjs')
            if bpjs_input:
                bpjs = Decimal(str(bpjs_input))
            else:
                bpjs = (honorarium * Decimal('0.01')).quantize(Decimal('1'))

            # Rumus 3: PPh 21
            pph21 = Decimal(str(request.POST.get('pph21') or 0))

            # Rumus 4: BPJS 4% (pemberi kerja)
            bpjs_pemberi_kerja_input = request.POST.get('bpjs_pemberi_kerja')
            if bpjs_pemberi_kerja_input:
                bpjs_pemberi_kerja = Decimal(str(bpjs_pemberi_kerja_input))
            else:
                bpjs_pemberi_kerja = (honorarium * Decimal('0.04')).quantize(Decimal('1'))

            # Rumus 5: BPJS Ketenagakerjaan
            bpjs_ketenagakerjaan = Decimal(str(request.POST.get('bpjs_ketenagakerjaan') or 0))

            if min(honorarium, potongan_kehadiran, bpjs, pph21, bpjs_pemberi_kerja, bpjs_ketenagakerjaan) < 0:
                messages.error(request, 'Nilai pembayaran tidak boleh negatif.')
                return redirect('laporan_detail', pk=laporan.pk)
            if potongan_kehadiran > honorarium:
                messages.error(request, 'Potongan absen tidak boleh lebih besar dari honorarium.')
                return redirect('laporan_detail', pk=laporan.pk)

            # Rumus 6: Nilai Bruto
            nilai_bruto = honorarium + bpjs_pemberi_kerja

            # Rumus 7: Total Diterima (Netto)
            total_diterima = jumlah_setelah_potongan_absen - bpjs - pph21
            if total_diterima < 0:
                total_diterima = Decimal(0)

        except Exception as e:
            messages.error(request, f'Format angka tidak valid: {e}')
            return redirect('laporan_detail', pk=laporan.pk)

        if pembayaran_id:
            pembayaran = get_object_or_404(Pembayaran, pk=pembayaran_id, laporan=laporan)
            pembayaran.honorarium = honorarium
            pembayaran.potongan_kehadiran = potongan_kehadiran
            pembayaran.jumlah_setelah_potongan_absen = jumlah_setelah_potongan_absen
            pembayaran.bpjs = bpjs
            pembayaran.pph21 = pph21
            pembayaran.bpjs_pemberi_kerja = bpjs_pemberi_kerja
            pembayaran.nilai_bruto = nilai_bruto
            pembayaran.bpjs_ketenagakerjaan = bpjs_ketenagakerjaan
            pembayaran.total_diterima = total_diterima
            pembayaran.save()
            messages.success(request, f'Data pembayaran untuk {pembayaran.pegawai.nama} berhasil diperbarui.')
        else:
            if not pegawai_id:
                messages.error(request, 'Pilih pegawai yang akan ditambahkan pembayarannya.')
                return redirect('laporan_detail', pk=laporan.pk)

            pegawai = get_object_or_404(Pegawai, pk=pegawai_id)

            if Pembayaran.objects.filter(laporan=laporan, pegawai=pegawai).exists():
                messages.warning(request, f'Pegawai {pegawai.nama} sudah tercatat dalam pembayaran periode ini.')
                return redirect('laporan_detail', pk=laporan.pk)

            Pembayaran.objects.create(
                laporan=laporan,
                pegawai=pegawai,
                honorarium=honorarium,
                potongan_kehadiran=potongan_kehadiran,
                jumlah_setelah_potongan_absen=jumlah_setelah_potongan_absen,
                bpjs=bpjs,
                pph21=pph21,
                bpjs_pemberi_kerja=bpjs_pemberi_kerja,
                nilai_bruto=nilai_bruto,
                bpjs_ketenagakerjaan=bpjs_ketenagakerjaan,
                total_diterima=total_diterima
            )
            messages.success(request, f'Pembayaran untuk {pegawai.nama} berhasil ditambahkan.')

    return redirect('laporan_detail', pk=laporan.pk)


@login_required(login_url='login')
def pembayaran_tambah_semua(request, laporan_id):
    laporan = get_object_or_404(LaporanBulanan, pk=laporan_id)

    if request.method == 'POST':
        default_honor = Decimal(str(request.POST.get('default_honor') or 7100000))
        pegawai_list = Pegawai.objects.all()

        added_count = 0
        for peg in pegawai_list:
            if not Pembayaran.objects.filter(laporan=laporan, pegawai=peg).exists():
                bpjs_1 = (default_honor * Decimal('0.01')).quantize(Decimal('1'))
                bpjs_4 = (default_honor * Decimal('0.04')).quantize(Decimal('1'))
                pph = Decimal(92779)
                netto = default_honor - bpjs_1 - pph

                Pembayaran.objects.create(
                    laporan=laporan,
                    pegawai=peg,
                    honorarium=default_honor,
                    potongan_kehadiran=Decimal(0),
                    jumlah_setelah_potongan_absen=default_honor,
                    bpjs=bpjs_1,
                    pph21=pph,
                    bpjs_pemberi_kerja=bpjs_4,
                    nilai_bruto=default_honor + bpjs_4,
                    bpjs_ketenagakerjaan=Decimal(38340),
                    total_diterima=netto
                )
                added_count += 1

        messages.success(request, f'Berhasil memasukkan {added_count} pegawai ke dalam daftar pembayaran bulan ini.')

    return redirect('laporan_detail', pk=laporan.pk)


@login_required(login_url='login')
def pembayaran_hapus(request, pk):
    pembayaran = get_object_or_404(Pembayaran, pk=pk)
    laporan_id = pembayaran.laporan_id
    if request.method == 'POST':
        pembayaran.delete()
        messages.success(request, 'Data pembayaran pegawai berhasil dihapus.')
    return redirect('laporan_detail', pk=laporan_id)


# =====================================================
# 5. KELOLA PENGATURAN LENGKAP & NOMOR DOKUMEN
# =====================================================

@login_required(login_url='login')
def laporan_pengaturan_simpan(request, laporan_id):
    """
    Menyimpan seluruh input teks dinamis (Warna Merah/Kuning/Biru dari dokumen contoh):
    - Seksi, PPTK, PPK, Bendahara, Tim TPPBJ
    - Program, Kegiatan, Sub Kegiatan, Aktivitas, Kode Rekening
    - Nama Pekerjaan, Volume, Nomor SPK & Tanggal SPK
    - Seluruh Nomor Surat Administrasi Kedinasan
    - Tanggal Surat, Tanggal Kwitansi, Waktu/Tempat Pemeriksaan
    """
    laporan = get_object_or_404(LaporanBulanan, pk=laporan_id)

    if request.method == 'POST':
        daftar_kunci = [
            # 1. Seksi & PPTK
            'nama_seksi', 'kode_seksi', 'pptk_nama', 'pptk_nip', 'pptk_jabatan',
            # 2. Klasifikasi Anggaran
            'program', 'kegiatan', 'sub_kegiatan', 'aktivitas', 'kode_rekening',
            # 3. Pekerjaan & SPK
            'nama_pekerjaan', 'volume', 'nomor_spk', 'tanggal_spk', 'tahun_anggaran',
            # 4. Nomor Dokumen Administrasi
            'permintaan_pemeriksaan', 'permintaan_teknis', 'undangan',
            'berita_acara_pemeriksaan', 'bast', 'bapp', 'kwitansi',
            # 5. Tanggal & Jadwal
            'tanggal_surat', 'hari_pembuatan', 'penyebutan_tanggal',
            'tanggal_kwitansi', 'waktu_pemeriksaan', 'tempat_pemeriksaan',
            # 6. Pejabat Penandatangan
            'ppk_nama', 'ppk_nip', 'bendahara_nama', 'bendahara_nip',
            'ppk_jabatan', 'bendahara_jabatan', 'pptk_jabatan_ttd',
            'tppbj_ketua', 'tppbj_ketua_nip', 'tppbj_sekretaris', 'tppbj_anggota', 'sk_tppbj'
        ]

        for kunci in daftar_kunci:
            val = request.POST.get(kunci)
            if val is not None:
                val = val.strip()
                nd, created = NomorDokumen.objects.get_or_create(
                    laporan=laporan,
                    jenis_dokumen=kunci,
                    defaults={'nomor_surat': val}
                )
                if not created:
                    nd.nomor_surat = val
                    nd.save()

        # Update juga objek Pekerjaan agar sinkron
        nama_pek = request.POST.get('nama_pekerjaan', '').strip()
        spk_no = request.POST.get('nomor_spk', '').strip()
        vol = request.POST.get('volume', '').strip()
        if nama_pek:
            pek = Pekerjaan.objects.filter(laporan=laporan).first()
            if pek:
                pek.nama_pekerjaan = nama_pek
                pek.nomor_spk = spk_no
                pek.volume = vol
                pek.save()
            else:
                Pekerjaan.objects.create(
                    laporan=laporan,
                    nama_pekerjaan=nama_pek,
                    nomor_spk=spk_no,
                    volume=vol
                )

        messages.success(request, 'Pengaturan laporan, klasifikasi anggaran, dan nomor dokumen berhasil disimpan ke database.')

    return redirect('laporan_detail', pk=laporan.pk)


@login_required(login_url='login')
def nomor_dokumen_simpan(request, laporan_id):
    """Alias kompatibilitas form nomor dokumen tab 3"""
    return laporan_pengaturan_simpan(request, laporan_id)


@login_required(login_url='login')
def laporan_terapkan_preset(request, laporan_id, preset_type):
    """
    1-Click Preset Penerapan Format Seksi:
    - astik : Seksi Aplikasi, Siber dan Statistik (Ibu Yuli Yanti - 01/PN.01.02)
    - id    : Seksi Infrastruktur Digital (Bapak Yasri Rahman M. - 10/PN.01.02)
    """
    laporan = get_object_or_404(LaporanBulanan, pk=laporan_id)
    bulan_int = laporan.bulan
    tahun_int = laporan.tahun
    bulan_nama = NAMA_BULAN.get(bulan_int, 'Oktober')
    romawi = BULAN_ROMAWI.get(bulan_int, 'X')
    bulan_berikut_idx = (bulan_int % 12) + 1
    bulan_berikut_nama = NAMA_BULAN.get(bulan_berikut_idx, 'November')

    if preset_type == 'astik':
        preset_data = {
            'nama_seksi': 'Seksi Aplikasi, Siber dan Statistik',
            'kode_seksi': 'ASTIK',
            'pptk_nama': 'Yuli Yanti',
            'pptk_nip': '197107251998032004',
            'pptk_jabatan': 'Kepala Seksi Aplikasi, Siber dan Statistik Suku Dinas Komunikasi, Informatika, dan Statistik Kota Administrasi Jakarta Pusat',
            'program': 'Program Penyelenggaraan Persandian Untuk Pengamanan Informasi',
            'kegiatan': 'Penyelenggaraan Persandian untuk Pengamanan Informasi Pemerintah Daerah Provinsi',
            'sub_kegiatan': 'Penyediaan Layanan Keamanan Informasi dan Persandian Pemerintah Daerah',
            'aktivitas': 'PJLP Layanan Keamanan Informasi',
            'kode_rekening': '5.1.02.02.001.00039 Belanja Jasa Tenaga Informasi dan Teknologi',
            'nama_pekerjaan': 'Petugas Informasi dan Teknologi-Aplication Support Kominfotik Technical Support',
            'volume': '1 BOK',
            'nomor_spk': '01/PN.01.02',
            'tanggal_spk': '2 Januari 2026',
            'tahun_anggaran': str(tahun_int),
            'permintaan_pemeriksaan': f"152/0006.0001/ASTIK/PJLP.KI/{romawi}/{tahun_int}",
            'permintaan_teknis': "1439/PN.01.02",
            'undangan': f"19/TPPBJ/KMFJP/ASTIK/0006.0001/{romawi}/{tahun_int}",
            'berita_acara_pemeriksaan': f"20/TPPBJ/KMFJP/ASTIK/PJLP.KI/{romawi}/{tahun_int}",
            'bast': "1440/PN.01.02",
            'bapp': "1441/PN.01.02",
            'kwitansi': f"88/KWT/ASTIK/0006.0001/XI/{tahun_int}",
            'tanggal_surat': f"30 {bulan_nama} {tahun_int}",
            'tanggal_kwitansi': f"02 {bulan_berikut_nama} {tahun_int}",
            'hari_pembuatan': 'Jumat',
            'penyebutan_tanggal': 'Tiga Puluh',
            'waktu_pemeriksaan': '16.30 s.d Selesai',
            'tempat_pemeriksaan': 'Sudin Kominfotik Kota Administrasi Jakarta Pusat',
            'ppk_nama': 'Rachmat Setiawan',
            'ppk_nip': '198102022006041009',
            'bendahara_nama': 'Roslaini Harahap',
            'bendahara_nip': '197203121993032007',
            'tppbj_ketua': 'Eka Novia Gunawan',
            'tppbj_ketua_nip': '198011082011011007',
            'tppbj_sekretaris': 'Reza Ayatuna Lazuardy',
            'tppbj_anggota': 'Sulaeman',
            'sk_tppbj': f"03 Tahun {tahun_int}",
        }
        seksi_label = "Seksi Aplikasi, Siber dan Statistik (ASTIK)"
    else:
        preset_data = {
            'nama_seksi': 'Seksi Infrastruktur Digital',
            'kode_seksi': 'ID',
            'pptk_nama': 'Yasri Rahman M.',
            'pptk_nip': '197808052011011008',
            'pptk_jabatan': 'Kepala Seksi Infrastruktur Digital Suku Dinas Komunikasi, Informatika, dan Statistik Kota Administrasi Jakarta Pusat',
            'program': 'Program Pengelolaan Aplikasi Informatika',
            'kegiatan': 'Pengelolaan E-government di Lingkup Pemerintah Daerah Provinsi',
            'sub_kegiatan': 'Penyelenggaraan Jaringan Intra Pemerintah Daerah Provinsi',
            'aktivitas': 'PJLP Jaringan Intra Pemerintah Daerah',
            'kode_rekening': '5.1.02.02.001.00039 Belanja Jasa Tenaga Informasi dan Teknologi',
            'nama_pekerjaan': 'Petugas Informasi dan Teknologi – Teknisi Jaringan Senior Kominfotik',
            'volume': '1 Orang 1 Bulan',
            'nomor_spk': '10/PN.01.02',
            'tanggal_spk': '02 Januari 2026',
            'tahun_anggaran': str(tahun_int),
            'permintaan_pemeriksaan': f"192/0030.0002/PJLP.ID/{romawi}/{tahun_int}",
            'permintaan_teknis': "1433/PN.01.02",
            'undangan': f"159/TPPBJ/KMFJP/ID/0030.0002/{romawi}/{tahun_int}",
            'berita_acara_pemeriksaan': f"160/TPPBJ/KMFJP/ID/0030.0002/{romawi}/{tahun_int}",
            'bast': "1434/PN.01.02",
            'bapp': "1435/PN.01.02",
            'kwitansi': f"88/KWT/ID/0030.0002/XI/{tahun_int}",
            'tanggal_surat': f"30 {bulan_nama} {tahun_int}",
            'tanggal_kwitansi': f"02 {bulan_berikut_nama} {tahun_int}",
            'hari_pembuatan': 'Jumat',
            'penyebutan_tanggal': 'Tiga Puluh',
            'waktu_pemeriksaan': '16.30 s.d Selesai',
            'tempat_pemeriksaan': 'Sudin Kominfotik Kota Administrasi Jakarta Pusat',
            'ppk_nama': 'Rachmat Setiawan',
            'ppk_nip': '198102022006041009',
            'bendahara_nama': 'Roslaini Harahap',
            'bendahara_nip': '197203121993032007',
            'tppbj_ketua': 'Eka Novia Gunawan',
            'tppbj_ketua_nip': '198011082011011007',
            'tppbj_sekretaris': 'Reza Ayatuna Lazuardy',
            'tppbj_anggota': 'Sulaeman',
            'sk_tppbj': f"03 Tahun {tahun_int}",
        }
        seksi_label = "Seksi Infrastruktur Digital (ID)"

    for k, v in preset_data.items():
        nd, created = NomorDokumen.objects.get_or_create(
            laporan=laporan,
            jenis_dokumen=k,
            defaults={'nomor_surat': v}
        )
        if not created:
            nd.nomor_surat = v
            nd.save()

    # Update objek pekerjaan
    pek = Pekerjaan.objects.filter(laporan=laporan).first()
    if pek:
        pek.nama_pekerjaan = preset_data['nama_pekerjaan']
        pek.nomor_spk = preset_data['nomor_spk']
        pek.volume = preset_data['volume']
        pek.save()
    else:
        Pekerjaan.objects.create(
            laporan=laporan,
            nama_pekerjaan=preset_data['nama_pekerjaan'],
            nomor_spk=preset_data['nomor_spk'],
            volume=preset_data['volume']
        )

    messages.success(request, f'Template format {seksi_label} berhasil diterapkan!')
    return redirect('laporan_detail', pk=laporan.pk)


@login_required(login_url='login')
def nomor_dokumen_pegawai_simpan(request, laporan_id, pegawai_id):
    """
    Menyimpan override nomor dokumen kedinasan khusus untuk seorang pegawai
    (misalnya nomor surat berurutan: 185, 186, 187, dst.)
    """
    laporan = get_object_or_404(LaporanBulanan, pk=laporan_id)
    pegawai = get_object_or_404(Pegawai, pk=pegawai_id)

    if request.method == 'POST':
        fields = ['no_jkd', 'no_tu1', 'no_tu2', 'no_tu3', 'no_tppbj1', 'no_tppbj2', 'no_kwt', 'spk']
        for f in fields:
            val = request.POST.get(f, '').strip()
            key_name = f"{f}_{pegawai.id}"
            nd, created = NomorDokumen.objects.get_or_create(
                laporan=laporan,
                jenis_dokumen=key_name,
                defaults={'nomor_surat': val}
            )
            if not created:
                nd.nomor_surat = val
                nd.save()

        messages.success(request, f'Nomor dokumen khusus untuk {pegawai.nama} berhasil disimpan ke database.')

    return redirect('laporan_detail', pk=laporan.pk)


# =====================================================
# 6. TANDA TANGAN DIGITAL (UPLOAD & DRAW CANVAS)
# =====================================================

PEJABAT_ROLES = ('pptk', 'ppk', 'bendahara')
MAKS_UKURAN_TTD = 3 * 1024 * 1024  # 3 MB


def _target_tanda_tangan(post):
    """Tentukan nama berkas TTD dari input yang sudah divalidasi (anti path traversal)."""
    tipe = post.get('target_type')
    if tipe == 'pegawai':
        pid = (post.get('pegawai_id') or '').strip()
        if pid.isdigit() and Pegawai.objects.filter(pk=int(pid)).exists():
            return f'pegawai_{int(pid)}.png', f'Pegawai {Pegawai.objects.get(pk=int(pid)).nama}'
    elif tipe == 'pejabat':
        role = (post.get('pejabat_role') or '').strip().lower()
        if role in PEJABAT_ROLES:
            return f'pejabat_{role}.png', f'Pejabat {role.upper()}'
    return None, None


def _normalisasi_tanda_tangan(raw):
    """Validasi gambar, jadikan PNG transparan (latar putih dihilangkan) dan crop ke goresan."""
    from PIL import Image
    import io as _io
    img = Image.open(_io.BytesIO(raw))
    img.verify()
    img = Image.open(_io.BytesIO(raw)).convert('RGBA')
    img.thumbnail((1200, 600))
    px = img.load()
    w, h = img.size
    for y in range(h):
        for x in range(w):
            r, g, b, a = px[x, y]
            lum = (r + g + b) / 3
            if lum > 235:
                px[x, y] = (r, g, b, 0)
            elif lum > 190:
                px[x, y] = (r, g, b, int(a * (235 - lum) / 45))
    box = img.getchannel('A').point(lambda v: 255 if v > 20 else 0).getbbox()
    if not box:
        raise ValueError('Gambar tanda tangan kosong.')
    pad = 6
    box = (max(box[0] - pad, 0), max(box[1] - pad, 0), min(box[2] + pad, w), min(box[3] + pad, h))
    out = _io.BytesIO()
    img.crop(box).save(out, format='PNG', optimize=True)
    return out.getvalue()


@login_required(login_url='login')
def tanda_tangan_gambar(request, nama_berkas):
    """Sajikan gambar tanda tangan dari database (pengganti folder media/)."""
    if not re.fullmatch(r'(pegawai_\d+|pejabat_(pptk|ppk|bendahara))\.png', nama_berkas):
        raise Http404()
    data = ttd_store.ambil(nama_berkas)
    if data is None:
        raise Http404()
    resp = HttpResponse(data, content_type='image/png')
    resp['Cache-Control'] = 'private, no-cache'
    return resp


@login_required(login_url='login')
def tanda_tangan_simpan(request, laporan_id):
    """
    Menyimpan tanda tangan digital (upload file ATAU gambar langsung dari canvas).
    Gambar divalidasi & dinormalisasi; disimpan ke media/signatures/.
    """
    laporan = get_object_or_404(LaporanBulanan, pk=laporan_id)
    if request.method != 'POST':
        return redirect('laporan_detail', pk=laporan.pk)

    filename, label = _target_tanda_tangan(request.POST)
    if not filename:
        messages.error(request, 'Target tanda tangan tidak valid.')
        return redirect('laporan_detail', pk=laporan.pk)

    canvas_data = request.POST.get('canvas_data') or ''
    uploaded = request.FILES.get('signature_file') or request.FILES.get('file_tanda_tangan')

    raw = None
    if 'base64,' in canvas_data:
        try:
            raw = base64.b64decode(canvas_data.split('base64,', 1)[1])
        except Exception:
            messages.error(request, 'Data goresan tanda tangan tidak valid.')
            return redirect('laporan_detail', pk=laporan.pk)
    elif uploaded:
        if uploaded.size > MAKS_UKURAN_TTD:
            messages.error(request, 'Ukuran berkas terlalu besar (maksimal 3 MB).')
            return redirect('laporan_detail', pk=laporan.pk)
        raw = uploaded.read()
    else:
        messages.warning(request, 'Tidak ada tanda tangan yang digambar atau berkas yang dipilih.')
        return redirect('laporan_detail', pk=laporan.pk)

    if len(raw) > MAKS_UKURAN_TTD:
        messages.error(request, 'Ukuran gambar terlalu besar (maksimal 3 MB).')
        return redirect('laporan_detail', pk=laporan.pk)
    try:
        png = _normalisasi_tanda_tangan(raw)
    except Exception:
        messages.error(request, 'Berkas bukan gambar yang valid. Gunakan PNG atau JPG.')
        return redirect('laporan_detail', pk=laporan.pk)

    ttd_store.simpan(filename, png)
    messages.success(request, f'Tanda tangan digital untuk {label} berhasil disimpan.')
    return redirect('laporan_detail', pk=laporan.pk)


@login_required(login_url='login')
def tanda_tangan_hapus(request, laporan_id):
    """Menghapus tanda tangan digital (dokumen kembali memakai ruang tanda tangan kosong)."""
    laporan = get_object_or_404(LaporanBulanan, pk=laporan_id)
    if request.method == 'POST':
        filename, _label = _target_tanda_tangan(request.POST)
        if filename:
            if ttd_store.hapus(filename):
                messages.info(request, 'Tanda tangan digital dihapus. Dokumen memakai ruang tanda tangan kosong.')
    return redirect('laporan_detail', pk=laporan.pk)


# =====================================================
# 7. GENERATE & UNDUH DOKUMEN WORD (.DOCX) SAMA PERSIS
# =====================================================

@login_required(login_url='login')
def generate_word(request, laporan_id):
    """
    Menghasilkan file Microsoft Word (.docx) yang SAMA PERSIS 100% dengan contoh_laporan.docx.
    Menerapkan seluruh parameter dinamis yang telah diatur oleh pengguna di aplikasi.
    Tanda tangan digital akan disematkan secara otomatis jika ada, dan jika tidak diisi tetap bisa diunduh dengan normal 100%!
    """
    laporan = get_object_or_404(LaporanBulanan, pk=laporan_id)

    data_pekerjaan = Pekerjaan.objects.filter(laporan=laporan).first()
    pembayaran_list = list(Pembayaran.objects.filter(laporan=laporan).select_related('pegawai').order_by('id'))
    nomor_dokumen_list = NomorDokumen.objects.filter(laporan=laporan)

    doc_numbers = {}
    for nd in nomor_dokumen_list:
        doc_numbers[nd.jenis_dokumen] = nd.nomor_surat

    mode = request.GET.get('mode') or request.POST.get('mode')
    pegawai_id = request.GET.get('pegawai_id') or request.POST.get('pegawai_id')

    # Mode 1: Unduh Semua Pegawai dalam format ZIP
    if mode == 'zip' or request.GET.get('all') == '1':
        if not pembayaran_list:
            messages.error(request, 'Belum ada data pegawai/pembayaran dalam laporan ini untuk diekspor.')
            return redirect('laporan_detail', pk=laporan.pk)

        zip_buffer = generate_all_pegawai_zip(
            laporan=laporan,
            pembayaran_list=pembayaran_list,
            pekerjaan=data_pekerjaan,
            doc_numbers=doc_numbers
        )
        zip_filename = f"Berkas_Laporan_{NAMA_BULAN.get(laporan.bulan, laporan.bulan)}_{laporan.tahun}_Semua_Pegawai.zip"
        response = HttpResponse(zip_buffer.getvalue(), content_type='application/zip')
        response['Content-Disposition'] = f'attachment; filename="{zip_filename}"'
        return response

    # Mode 2: Unduh Dokumen untuk Pegawai Spesifik
    target_pegawai = None
    target_pembayaran = None

    if pegawai_id:
        target_pegawai = get_object_or_404(Pegawai, pk=pegawai_id)
        target_pembayaran = Pembayaran.objects.filter(laporan=laporan, pegawai=target_pegawai).first()
    elif pembayaran_list:
        target_pembayaran = pembayaran_list[0]
        target_pegawai = target_pembayaran.pegawai
    else:
        # Fallback default pegawai jika belum ada pembayaran di DB
        target_pegawai = Pegawai.objects.filter(nama__icontains='Achmad').first() or Pegawai.objects.filter(nama__icontains='Faris').first() or Pegawai.objects.first()

    docx_buffer = generate_exact_word_docx(
        laporan=laporan,
        pegawai=target_pegawai,
        pembayaran=target_pembayaran,
        pekerjaan=data_pekerjaan,
        doc_numbers=doc_numbers
    )

    nama_bersih = target_pegawai.nama.replace(' ', '_') if target_pegawai else 'Pegawai'
    doc_filename = f"Laporan_{nama_bersih}_{NAMA_BULAN.get(laporan.bulan, laporan.bulan)}_{laporan.tahun}.docx"

    response = HttpResponse(
        docx_buffer.getvalue(),
        content_type='application/vnd.openxmlformats-officedocument.wordprocessingml.document'
    )
    response['Content-Disposition'] = f'attachment; filename="{doc_filename}"'
    return response


# =====================================================
# 8. SEED DATA RESMI (PENGUJIAN & IMPOR AWAL)
# =====================================================

@login_required(login_url='login')
def seed_contoh_data(request):
    """
    Alat bantu pengujian (seeder): Memuat data contoh kedinasan untuk pengujian instan format Word.
    """
    laporan = LaporanBulanan.objects.filter(bulan=10, tahun=2026).order_by('id').first()
    if not laporan:
        laporan = LaporanBulanan.objects.create(
            bulan=10, tahun=2026,
            tanggal_mulai=datetime.date(2026, 10, 1),
            tanggal_selesai=datetime.date(2026, 10, 30),
            status='draft',
            created_at=timezone.now()
        )

    # 1. PEGAWAI DARI CONTOH DOC (SEKSI ASTIK - Achmad Febriansyah)
    peg_astik, _ = Pegawai.objects.get_or_create(
        id_phl='80761851',
        defaults={
            'nama': 'Achmad Febriansyah',
            'jabatan': 'Petugas Informasi dan Teknologi-Aplication Support Kominfotik Technical Support',
            'alamat': 'Jl. Pengadegan Timur RT 006 / RW 01, Kel. Pengadegan Kec.Pancoran, Jakarta Selatan',
            'nomor_rekening': '111.23.15165.1',
            'npwp': '74.785.391.9-061.000'
        }
    )

    # 2. 8 PEGAWAI DARI CONTOH EXCEL (SEKSI ID)
    DATA_PEGAWAI_ID = [
        {
            'id_phl': '80752759', 'nama': 'Emir Fathan',
            'alamat': 'Kp Sungkaeun RT.004 RW.004 , Kelurahan Pabuaran, Kecamatan Rangkasbitung, Lebak',
            'nomor_rekening': '111.23.11099.8', 'npwp': '86.906.248.9-445.000',
            'jabatan': 'Petugas Informasi dan Teknologi – Teknisi Jaringan Senior Kominfotik',
            'gaji': Decimal('8005000'), 'spk': '03/PN.01.02', 'pph': Decimal('83684'),
            'bpjs1': Decimal('80050'), 'bpjs4': Decimal('320200'), 'bpjs_naker': Decimal('43227'),
            'pot_absen': Decimal('0'), 'nilai_bruto': Decimal('8325200'), 'total_diterima': Decimal('7841266'),
            'no_jkd': '185/0030.0002/PJLP.ID/X/2026', 'no_tu1': '1412/PN.01.02', 'no_tu2': '1413/PN.01.02',
            'no_tu3': '1414/PN.01.02', 'no_tppbj1': '145/TPPBJ/KMFJP/ID/0030.0002/X/2026',
            'no_tppbj2': '146/TPPBJ/KMFJP/ID/0030.0002/X/2026', 'no_kwt': '81/KWT/ID/0030.0002/XI/2026'
        },
        {
            'id_phl': '80756167', 'nama': 'Firman Alamsyah',
            'alamat': 'Jl. Keamanan Dalam II/3A RT. 008 RW. 008, Kelurahan Keagungan, Kecamatan Taman Sari, Jakarta Barat',
            'nomor_rekening': '111.20.21429.6', 'npwp': '86.847.268.9-037.000',
            'jabatan': 'Petugas Informasi dan Teknologi – Teknisi Jaringan Senior Kominfotik',
            'gaji': Decimal('8005000'), 'spk': '04/PN.01.02', 'pph': Decimal('83684'),
            'bpjs1': Decimal('80050'), 'bpjs4': Decimal('320200'), 'bpjs_naker': Decimal('43227'),
            'pot_absen': Decimal('0'), 'nilai_bruto': Decimal('8325200'), 'total_diterima': Decimal('7841266'),
            'no_jkd': '186/0030.0002/PJLP.ID/X/2026', 'no_tu1': '1415/PN.01.02', 'no_tu2': '1416/PN.01.02',
            'no_tu3': '1417/PN.01.02', 'no_tppbj1': '147/TPPBJ/KMFJP/ID/0030.0002/X/2026',
            'no_tppbj2': '148/TPPBJ/KMFJP/ID/0030.0002/X/2026', 'no_kwt': '82/KWT/ID/0030.0002/XI/2026'
        },
        {
            'id_phl': '80760564', 'nama': 'Fikri Alwan',
            'alamat': 'Bendungan Jago RT. 009 RW. 002, Kelurahan Serdang, Kecamatan Kemayoran, Jakarta Pusat',
            'nomor_rekening': '509.20.52244.0', 'npwp': '94.219.814.4-027.000',
            'jabatan': 'Petugas Informasi dan Teknologi – Teknisi Jaringan Senior Kominfotik',
            'gaji': Decimal('8005000'), 'spk': '05/PN.01.02', 'pph': Decimal('125526'),
            'bpjs1': Decimal('80050'), 'bpjs4': Decimal('320200'), 'bpjs_naker': Decimal('43227'),
            'pot_absen': Decimal('0'), 'nilai_bruto': Decimal('8325200'), 'total_diterima': Decimal('7799424'),
            'no_jkd': '187/0030.0002/PJLP.ID/X/2026', 'no_tu1': '1418/PN.01.02', 'no_tu2': '1419/PN.01.02',
            'no_tu3': '1420/PN.01.02', 'no_tppbj1': '149/TPPBJ/KMFJP/ID/0030.0002/X/2026',
            'no_tppbj2': '150/TPPBJ/KMFJP/ID/0030.0002/X/2026', 'no_kwt': '83/KWT/ID/0030.0002/XI/2026'
        },
        {
            'id_phl': '80760680', 'nama': 'Ahmad Fahmi Adam',
            'alamat': 'Jl. GN Sahari X/DLM RT. 012 RW. 003, Kelurahan Gunung Sahari Utara, Kecamatan Sawah Besar, Jakarta Pusat',
            'nomor_rekening': '104.23.11700.1', 'npwp': '74.106.435.6-026.000',
            'jabatan': 'Petugas Informasi dan Teknologi – Teknisi Jaringan Senior Kominfotik',
            'gaji': Decimal('7800000'), 'spk': '06/PN.01.02', 'pph': Decimal('122312'),
            'bpjs1': Decimal('78000'), 'bpjs4': Decimal('312000'), 'bpjs_naker': Decimal('42120'),
            'pot_absen': Decimal('0'), 'nilai_bruto': Decimal('8112000'), 'total_diterima': Decimal('7599688'),
            'no_jkd': '188/0030.0002/PJLP.ID/X/2026', 'no_tu1': '1421/PN.01.02', 'no_tu2': '1422/PN.01.02',
            'no_tu3': '1423/PN.01.02', 'no_tppbj1': '151/TPPBJ/KMFJP/ID/0030.0002/X/2026',
            'no_tppbj2': '152/TPPBJ/KMFJP/ID/0030.0002/X/2026', 'no_kwt': '84/KWT/ID/0030.0002/XI/2026'
        },
        {
            'id_phl': '80760888', 'nama': 'Yoga Pratama',
            'alamat': 'Jl. Mampang Prapatan VI/D RT. 004 RW. 002, Kelurahan Tegal Parang, Kecamatan Mampang Prapatan, Jakarta Selatan',
            'nomor_rekening': '300.23.31877.4', 'npwp': '90.820.932.3-014.000',
            'jabatan': 'Petugas Informasi dan Teknologi – Teknisi Jaringan Senior Kominfotik',
            'gaji': Decimal('7600000'), 'spk': '7/PN.01.02', 'pph': Decimal('119176'),
            'bpjs1': Decimal('76000'), 'bpjs4': Decimal('304000'), 'bpjs_naker': Decimal('41040'),
            'pot_absen': Decimal('0'), 'nilai_bruto': Decimal('7904000'), 'total_diterima': Decimal('7404824'),
            'no_jkd': '189/0030.0002/PJLP.ID/X/2026', 'no_tu1': '1424/PN.01.02', 'no_tu2': '1425/PN.01.02',
            'no_tu3': '1426/PN.01.02', 'no_tppbj1': '153/TPPBJ/KMFJP/ID/0030.0002/X/2026',
            'no_tppbj2': '154/TPPBJ/KMFJP/ID/0030.0002/X/2026', 'no_kwt': '85/KWT/ID/0030.0002/XI/2026'
        },
        {
            'id_phl': '80761331', 'nama': 'Revando Prastya',
            'alamat': 'Jl. H. Junaidi RT.008 RW.011, Kelurahan Palmerah, Kecamatan Palmerah, Jakarta Barat',
            'nomor_rekening': '116.23.54392.5', 'npwp': '90.882.111.9-031.000',
            'jabatan': 'Petugas Informasi dan Teknologi – Teknisi Jaringan Senior Kominfotik',
            'gaji': Decimal('7400000'), 'spk': '8/PN.01.02', 'pph': Decimal('116039'),
            'bpjs1': Decimal('74000'), 'bpjs4': Decimal('296000'), 'bpjs_naker': Decimal('39960'),
            'pot_absen': Decimal('0'), 'nilai_bruto': Decimal('7696000'), 'total_diterima': Decimal('7209961'),
            'no_jkd': '190/0030.0002/PJLP.ID/X/2026', 'no_tu1': '1427/PN.01.02', 'no_tu2': '1428/PN.01.02',
            'no_tu3': '1429/PN.01.02', 'no_tppbj1': '155/TPPBJ/KMFJP/ID/0030.0002/X/2026',
            'no_tppbj2': '156/TPPBJ/KMFJP/ID/0030.0002/X/2026', 'no_kwt': '86/KWT/ID/0030.0002/XI/2026'
        },
        {
            'id_phl': '80761405', 'nama': 'Fauzan Agrinanto',
            'alamat': 'Jl. Bangka IX B/7A RT. 010 RW. 010, Kelurahan Pela Mampang, Kecamatan Mampang Prapatan, Jakarta Selatan',
            'nomor_rekening': '111.23.15115.5', 'npwp': '53.580.622.8-014.000',
            'jabatan': 'Petugas Informasi dan Teknologi – Teknisi Jaringan Senior Kominfotik',
            'gaji': Decimal('7400000'), 'spk': '9/PN.01.02', 'pph': Decimal('116039'),
            'bpjs1': Decimal('74000'), 'bpjs4': Decimal('296000'), 'bpjs_naker': Decimal('39960'),
            'pot_absen': Decimal('0'), 'nilai_bruto': Decimal('7696000'), 'total_diterima': Decimal('7209961'),
            'no_jkd': '191/0030.0002/PJLP.ID/X/2026', 'no_tu1': '1430/PN.01.02', 'no_tu2': '1431/PN.01.02',
            'no_tu3': '1432/PN.01.02', 'no_tppbj1': '157/TPPBJ/KMFJP/ID/0030.0002/X/2026',
            'no_tppbj2': '158/TPPBJ/KMFJP/ID/0030.0002/X/2026', 'no_kwt': '87/KWT/ID/0030.0002/XI/2026'
        },
        {
            'id_phl': '80901744', 'nama': 'Faris Ibnu Hasan',
            'alamat': 'Perum Pesona Laguna Blk C6 No.2 RT.003 RW.020 Kelurahan Cilangkap, Kecamatan Tapos, Depok',
            'nomor_rekening': '530.28.00279.6', 'npwp': '12.803.533.4-412.000',
            'jabatan': 'Petugas Informasi dan Teknologi – Teknisi Jaringan Senior Kominfotik',
            'gaji': Decimal('7100000'), 'spk': '10/PN.01.02', 'pph': Decimal('92779'),
            'bpjs1': Decimal('71000'), 'bpjs4': Decimal('284000'), 'bpjs_naker': Decimal('38340'),
            'pot_absen': Decimal('0'), 'nilai_bruto': Decimal('7384000'), 'total_diterima': Decimal('6936221'),
            'no_jkd': '192/0030.0002/PJLP.ID/X/2026', 'no_tu1': '1433/PN.01.02', 'no_tu2': '1434/PN.01.02',
            'no_tu3': '1435/PN.01.02', 'no_tppbj1': '159/TPPBJ/KMFJP/ID/0030.0002/X/2026',
            'no_tppbj2': '160/TPPBJ/KMFJP/ID/0030.0002/X/2026', 'no_kwt': '88/KWT/ID/0030.0002/XI/2026'
        }
    ]

    for item in DATA_PEGAWAI_ID:
        p, _ = Pegawai.objects.get_or_create(
            id_phl=item['id_phl'],
            defaults={
                'nama': item['nama'],
                'jabatan': item['jabatan'],
                'alamat': item['alamat'],
                'nomor_rekening': item['nomor_rekening'],
                'npwp': item['npwp']
            }
        )

        Pembayaran.objects.get_or_create(
            laporan=laporan,
            pegawai=p,
            defaults={
                'honorarium': item['gaji'],
                'potongan_kehadiran': item['pot_absen'],
                'jumlah_setelah_potongan_absen': item['gaji'] - item['pot_absen'],
                'bpjs': item['bpjs1'],
                'pph21': item['pph'],
                'bpjs_pemberi_kerja': item['bpjs4'],
                'nilai_bruto': item['nilai_bruto'],
                'bpjs_ketenagakerjaan': item['bpjs_naker'],
                'total_diterima': item['total_diterima']
            }
        )

        NomorDokumen.objects.update_or_create(laporan=laporan, jenis_dokumen=f'no_jkd_{p.id}', defaults={'nomor_surat': item['no_jkd']})
        NomorDokumen.objects.update_or_create(laporan=laporan, jenis_dokumen=f'no_tu1_{p.id}', defaults={'nomor_surat': item['no_tu1']})
        NomorDokumen.objects.update_or_create(laporan=laporan, jenis_dokumen=f'no_tu2_{p.id}', defaults={'nomor_surat': item['no_tu2']})
        NomorDokumen.objects.update_or_create(laporan=laporan, jenis_dokumen=f'no_tu3_{p.id}', defaults={'nomor_surat': item['no_tu3']})
        NomorDokumen.objects.update_or_create(laporan=laporan, jenis_dokumen=f'no_tppbj1_{p.id}', defaults={'nomor_surat': item['no_tppbj1']})
        NomorDokumen.objects.update_or_create(laporan=laporan, jenis_dokumen=f'no_tppbj2_{p.id}', defaults={'nomor_surat': item['no_tppbj2']})
        NomorDokumen.objects.update_or_create(laporan=laporan, jenis_dokumen=f'no_kwt_{p.id}', defaults={'nomor_surat': item['no_kwt']})
        NomorDokumen.objects.update_or_create(laporan=laporan, jenis_dokumen=f'spk_{p.id}', defaults={'nomor_surat': item['spk']})

    # Simpan pembayaran untuk Achmad Febriansyah (ASTIK)
    pb_astik, _ = Pembayaran.objects.get_or_create(
        laporan=laporan,
        pegawai=peg_astik,
        defaults={
            'honorarium': Decimal('7700000'),
            'potongan_kehadiran': Decimal('0'),
            'jumlah_setelah_potongan_absen': Decimal('7700000'),
            'bpjs': Decimal('77000'),
            'pph21': Decimal('0'),
            'bpjs_pemberi_kerja': Decimal('308000'),
            'nilai_bruto': Decimal('8049580'),
            'bpjs_ketenagakerjaan': Decimal('41580'),
            'total_diterima': Decimal('7623000')
        }
    )
    NomorDokumen.objects.update_or_create(laporan=laporan, jenis_dokumen=f'no_jkd_{peg_astik.id}', defaults={'nomor_surat': '152/0006.0001/ASTIK/PJLP.KI/X/2026'})
    NomorDokumen.objects.update_or_create(laporan=laporan, jenis_dokumen=f'no_tu1_{peg_astik.id}', defaults={'nomor_surat': '1439/PN.01.02'})
    NomorDokumen.objects.update_or_create(laporan=laporan, jenis_dokumen=f'no_tu2_{peg_astik.id}', defaults={'nomor_surat': '1440/PN.01.02'})
    NomorDokumen.objects.update_or_create(laporan=laporan, jenis_dokumen=f'no_tu3_{peg_astik.id}', defaults={'nomor_surat': '1441/PN.01.02'})
    NomorDokumen.objects.update_or_create(laporan=laporan, jenis_dokumen=f'no_tppbj1_{peg_astik.id}', defaults={'nomor_surat': '19/TPPBJ/KMFJP/ASTIK/0006.0001/X/2026'})
    NomorDokumen.objects.update_or_create(laporan=laporan, jenis_dokumen=f'no_tppbj2_{peg_astik.id}', defaults={'nomor_surat': '20/TPPBJ/KMFJP/ASTIK/PJLP.KI/X/2026'})
    NomorDokumen.objects.update_or_create(laporan=laporan, jenis_dokumen=f'spk_{peg_astik.id}', defaults={'nomor_surat': '01/PN.01.02'})

    laporan_terapkan_preset(request, laporan.id, 'astik')

    messages.success(request, 'Berhasil memuat data contoh (Data ASTIK & ID) ke database!')
    return redirect('laporan_detail', pk=laporan.pk)


# =====================================================
# 9. MASTER PEGAWAI CRUD
# =====================================================

@login_required(login_url='login')
def pegawai_list(request):
    query = request.GET.get('q', '').strip()
    if query:
        pegawai_all = Pegawai.objects.filter(
            nama__icontains=query
        ) | Pegawai.objects.filter(
            id_phl__icontains=query
        ) | Pegawai.objects.filter(
            jabatan__icontains=query
        )
    else:
        pegawai_all = Pegawai.objects.all().order_by('nama')

    context = {
        'pegawai_list': pegawai_all,
        'query': query,
        'total_pegawai': Pegawai.objects.count()
    }
    return render(request, 'pegawai/list.html', context)


@login_required(login_url='login')
def pegawai_tambah(request):
    if request.method == 'POST':
        id_phl = request.POST.get('id_phl', '').strip()
        nama = request.POST.get('nama', '').strip()
        jabatan = request.POST.get('jabatan', '').strip()
        nip = request.POST.get('nip', '').strip()
        npwp = request.POST.get('npwp', '').strip()
        nomor_rekening = request.POST.get('nomor_rekening', '').strip()
        alamat = request.POST.get('alamat', '').strip()

        if not nama:
            messages.error(request, 'Nama pegawai wajib diisi.')
            return render(request, 'pegawai/form.html')

        Pegawai.objects.create(
            id_phl=id_phl or None,
            nama=nama,
            jabatan=jabatan or None,
            nip=nip or None,
            npwp=npwp or None,
            nomor_rekening=nomor_rekening or None,
            alamat=alamat or None
        )

        messages.success(request, f'Pegawai {nama} berhasil ditambahkan ke database.')
        return redirect('pegawai_list')

    return render(request, 'pegawai/form.html')


@login_required(login_url='login')
def pegawai_edit(request, pk):
    pegawai = get_object_or_404(Pegawai, pk=pk)

    if request.method == 'POST':
        id_phl = request.POST.get('id_phl', '').strip()
        nama = request.POST.get('nama', '').strip()
        jabatan = request.POST.get('jabatan', '').strip()
        nip = request.POST.get('nip', '').strip()
        npwp = request.POST.get('npwp', '').strip()
        nomor_rekening = request.POST.get('nomor_rekening', '').strip()
        alamat = request.POST.get('alamat', '').strip()

        if not nama:
            messages.error(request, 'Nama pegawai wajib diisi.')
            return render(request, 'pegawai/form.html', {'pegawai': pegawai})

        pegawai.id_phl = id_phl or None
        pegawai.nama = nama
        pegawai.jabatan = jabatan or None
        pegawai.nip = nip or None
        pegawai.npwp = npwp or None
        pegawai.nomor_rekening = nomor_rekening or None
        pegawai.alamat = alamat or None
        pegawai.save()

        messages.success(request, f'Data pegawai {nama} berhasil diperbarui di database.')
        return redirect('pegawai_list')

    return render(request, 'pegawai/form.html', {'pegawai': pegawai})


@login_required(login_url='login')
def pegawai_hapus(request, pk):
    pegawai = get_object_or_404(Pegawai, pk=pk)

    # Validasi proteksi riwayat: jangan hapus jika sudah ada di pembayaran
    ada_di_pembayaran = Pembayaran.objects.filter(pegawai=pegawai).exists()
    if ada_di_pembayaran:
        messages.error(
            request,
            f'Pegawai {pegawai.nama} tidak dapat dihapus karena tercatat dalam riwayat laporan bulanan. '
            f'Hapus data pembayaran terkait terlebih dahulu jika ingin menghapusnya.'
        )
        return redirect('pegawai_list')

    if request.method == 'POST':
        nama = pegawai.nama
        pegawai.delete()
        messages.success(request, f'Pegawai {nama} berhasil dihapus dari sistem database.')
        return redirect('pegawai_list')

    return render(request, 'pegawai/konfirmasi_hapus.html', {'pegawai': pegawai})
