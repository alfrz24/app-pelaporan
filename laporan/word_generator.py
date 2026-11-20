"""
word_generator.py - Modul Generator Dokumen Word (.docx) Otomatis
Menggunakan template resmi contoh_laporan.docx sebagai master template
sehingga hasil output dijamin SAMA PERSIS 100% dengan format dokumen asli:
- Logo Jaya Raya DKI Jakarta
- Tata letak, margin, font, dan spasi
- Susunan 12 halaman/lembar dokumen kedinasan
- Tabel dan nomor dokumen
- Mendukung kustomisasi penuh seluruh teks berwarna (Red/Yellow/Blue):
  * Seksi & PPTK (ASTIK / ID / custom)
  * Program, Kegiatan, Sub Kegiatan, Aktivitas, Kode Rekening
  * Nama Pekerjaan, Volume, Nomor SPK & Tanggal SPK
  * Tanggal BAST, Hari, Tanggal Kwitansi, Waktu/Tempat Pemeriksaan
  * Seluruh nomor surat kedinasan (global maupun per-pegawai)
  * Pejabat PPK, PPTK, Bendahara, Tim TPPBJ
"""

import io
import re
import os
import zipfile
from decimal import Decimal
from pathlib import Path
from django.conf import settings

BASE_DIR = Path(__file__).resolve().parent.parent
TEMPLATE_PATH = BASE_DIR / 'laporan' / 'template_docx' / 'contoh_laporan.docx'

NAMA_BULAN = {
    1: 'Januari', 2: 'Februari', 3: 'Maret', 4: 'April',
    5: 'Mei', 6: 'Juni', 7: 'Juli', 8: 'Agustus',
    9: 'September', 10: 'Oktober', 11: 'November', 12: 'Desember'
}

PENYEBUTAN_ANGKA = {
    1: 'Satu', 2: 'Dua', 3: 'Tiga', 4: 'Empat', 5: 'Lima',
    6: 'Enam', 7: 'Tujuh', 8: 'Delapan', 9: 'Sembilan', 10: 'Sepuluh',
    11: 'Sebelas', 12: 'Dua Belas', 13: 'Tiga Belas', 14: 'Empat Belas',
    15: 'Lima Belas', 16: 'Enam Belas', 17: 'Tujuh Belas', 18: 'Delapan Belas',
    19: 'Sembilan Belas', 20: 'Dua Puluh', 21: 'Dua Puluh Satu', 22: 'Dua Puluh Dua',
    23: 'Dua Puluh Tiga', 24: 'Dua Puluh Empat', 25: 'Dua Puluh Lima', 26: 'Dua Puluh Enam',
    27: 'Dua Puluh Tujuh', 28: 'Dua Puluh Delapan', 29: 'Dua Puluh Sembilan', 30: 'Tiga Puluh',
    31: 'Tiga Puluh Satu'
}

HARI_NAMA = {
    0: 'Senin', 1: 'Selasa', 2: 'Rabu', 3: 'Kamis',
    4: 'Jumat', 5: 'Sabtu', 6: 'Minggu'
}

BULAN_ROMAWI = {
    1: 'I', 2: 'II', 3: 'III', 4: 'IV', 5: 'V', 6: 'VI',
    7: 'VII', 8: 'VIII', 9: 'IX', 10: 'X', 11: 'XI', 12: 'XII'
}

def escape_xml(text):
    if text is None:
        return ''
    s = str(text)
    return s.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;').replace('"', '&quot;').replace("'", '&apos;')

def format_rupiah_standard(nilai):
    """Format: 7.100.000,- (sesuai contoh resmi)"""
    if nilai is None:
        return '0,-'
    try:
        val = int(round(Decimal(str(nilai))))
        s = f"{val:,}".replace(',', '.')
        return f"{s},-"
    except Exception:
        return f"{nilai}"

def terbilang(n, uppercase=False):
    """Mengubah nominal uang ke teks terbilang bahasa Indonesia"""
    try:
        n = int(round(Decimal(str(n or 0))))
    except Exception:
        return "NOL RUPIAH" if uppercase else "Nol Rupiah"

    if n == 0:
        return "NOL RUPIAH" if uppercase else "Nol Rupiah"

    satuan = ["", "Satu", "Dua", "Tiga", "Empat", "Lima", "Enam", "Tujuh", "Delapan", "Sembilan", "Sepuluh", "Sebelas"]

    def sebut(x):
        if x < 12:
            return satuan[x]
        elif x < 20:
            return sebut(x - 10) + " Belas"
        elif x < 100:
            return sebut(x // 10) + " Puluh " + sebut(x % 10)
        elif x < 200:
            return "Seratus " + sebut(x - 100)
        elif x < 1000:
            return sebut(x // 100) + " Ratus " + sebut(x % 100)
        elif x < 2000:
            return "Seribu " + sebut(x - 1000)
        elif x < 1000000:
            return sebut(x // 1000) + " Ribu " + sebut(x % 1000)
        elif x < 1000000000:
            return sebut(x // 1000000) + " Juta " + sebut(x % 1000000)
        elif x < 1000000000000:
            return sebut(x // 1000000000) + " Miliar " + sebut(x % 1000000000)
        elif x < 1000000000000000:
            return sebut(x // 1000000000000) + " Triliun " + sebut(x % 1000000000000)
        return ""

    hasil = ' '.join(sebut(n).split()) + " Rupiah"
    if uppercase:
        return hasil.upper()
    return hasil

def build_merge_replacements(laporan, pegawai, pembayaran=None, pekerjaan=None, doc_numbers=None):
    """
    Menyiapkan kamus nilai pengganti untuk seluruh 34 MERGEFIELD di contoh_laporan.docx
    serta membaca override khusus per-pegawai jika tersedia.
    """
    doc_numbers = doc_numbers or {}
    bulan_int = laporan.bulan
    tahun_int = laporan.tahun
    bulan_nama = NAMA_BULAN.get(bulan_int, 'Oktober')
    romawi = BULAN_ROMAWI.get(bulan_int, 'X')
    pegawai_id = pegawai.id if pegawai else 0

    # 1. Tanggal Pembuatan BAST & Hari
    if doc_numbers.get('tanggal_surat'):
        tanggal_pembuatan_bast = doc_numbers.get('tanggal_surat')
        hari_str = doc_numbers.get('hari_pembuatan') or 'Jumat'
        penyebutan_tanggal = doc_numbers.get('penyebutan_tanggal') or 'Tiga Puluh'
    elif laporan.tanggal_selesai:
        tgl_bast_day = laporan.tanggal_selesai.day
        hari_str = HARI_NAMA.get(laporan.tanggal_selesai.weekday(), 'Jumat')
        tanggal_pembuatan_bast = f"{tgl_bast_day} {bulan_nama} {tahun_int}"
        penyebutan_tanggal = PENYEBUTAN_ANGKA.get(tgl_bast_day, 'Tiga Puluh')
    else:
        tgl_bast_day = 30
        hari_str = 'Jumat'
        tanggal_pembuatan_bast = f"{tgl_bast_day} {bulan_nama} {tahun_int}"
        penyebutan_tanggal = PENYEBUTAN_ANGKA.get(tgl_bast_day, 'Tiga Puluh')

    penyebutan_bulan = bulan_nama

    # 2. Data Pegawai
    nama_ta = pegawai.nama if pegawai else 'Faris Ibnu Hasan'
    id_phl = pegawai.id_phl if (pegawai and pegawai.id_phl) else '80901744'
    alamat_ta = pegawai.alamat if (pegawai and pegawai.alamat) else 'Perum Pesona Laguna Blk C6 No.2 RT.003 RW.020 Kelurahan Cilangkap, Kecamatan Tapos, Depok'
    no_rek = pegawai.nomor_rekening if (pegawai and pegawai.nomor_rekening) else '530.28.00279.6'
    npwp = pegawai.npwp if (pegawai and pegawai.npwp) else '12.803.533.4-412.000'

    # 3. SPK Nomor & Tanggal (prioritas: doc_numbers khusus pegawai > pekerjaan > default)
    spk_nomor = doc_numbers.get(f'spk_{pegawai_id}') or '10/PN.01.02'
    spk_tgl = '02 Januari 2026'
    if pekerjaan:
        spk_nomor = doc_numbers.get(f'spk_{pegawai_id}') or pekerjaan.nomor_spk or spk_nomor
        if pekerjaan.tanggal_spk:
            spk_tgl = pekerjaan.tanggal_spk.strftime('%d %B %Y')

    if doc_numbers.get('tanggal_spk'):
        spk_tgl = doc_numbers.get('tanggal_spk')

    # 4. Data Keuangan & Pembayaran
    if pembayaran:
        gaji = pembayaran.honorarium if pembayaran.honorarium is not None else Decimal(7100000)
        pot_absen = pembayaran.potongan_kehadiran if pembayaran.potongan_kehadiran is not None else Decimal(0)
        set_pot = pembayaran.jumlah_setelah_potongan_absen if pembayaran.jumlah_setelah_potongan_absen is not None else (gaji - pot_absen)
        bpjs1 = pembayaran.bpjs if pembayaran.bpjs is not None else (gaji * Decimal('0.01'))
        pph = pembayaran.pph21 if pembayaran.pph21 is not None else Decimal(92779)
        bpjs4 = pembayaran.bpjs_pemberi_kerja if pembayaran.bpjs_pemberi_kerja is not None else (gaji * Decimal('0.04'))
        bpjs_naker = pembayaran.bpjs_ketenagakerjaan if pembayaran.bpjs_ketenagakerjaan is not None else Decimal(38340)
        nilai_bruto = pembayaran.nilai_bruto if pembayaran.nilai_bruto is not None else (gaji + bpjs4)
        jumlah_diterima = pembayaran.total_diterima if pembayaran.total_diterima is not None else (set_pot - bpjs1 - pph)
    else:
        gaji = Decimal(7100000)
        pot_absen = Decimal(0)
        set_pot = Decimal(7100000)
        bpjs1 = Decimal(71000)
        pph = Decimal(92779)
        bpjs4 = Decimal(284000)
        bpjs_naker = Decimal(38340)
        nilai_bruto = Decimal(7384000)
        jumlah_diterima = Decimal(6936221)

    terbilang_1 = terbilang(gaji, uppercase=False)
    terbilang_2 = terbilang(gaji, uppercase=True)

    # 5. Nomor Dokumen (cek override khusus pegawai terlebih dahulu)
    kode_seksi = doc_numbers.get('kode_seksi', 'ID').upper()
    prefix_sub = '0006.0001' if 'ASTIK' in kode_seksi else '0030.0002'

    no_seksi_jkd = (
        doc_numbers.get(f'no_jkd_{pegawai_id}') or
        doc_numbers.get('permintaan_pemeriksaan') or
        (f"152/{prefix_sub}/{kode_seksi}/PJLP.KI/{romawi}/{tahun_int}" if 'ASTIK' in kode_seksi else f"192/{prefix_sub}/PJLP.ID/{romawi}/{tahun_int}")
    )
    no_tu_1 = doc_numbers.get(f'no_tu1_{pegawai_id}') or doc_numbers.get('permintaan_teknis') or ("1439/PN.01.02" if 'ASTIK' in kode_seksi else "1433/PN.01.02")
    no_tu_2 = doc_numbers.get(f'no_tu2_{pegawai_id}') or doc_numbers.get('bast') or ("1440/PN.01.02" if 'ASTIK' in kode_seksi else "1434/PN.01.02")
    no_tu_3 = doc_numbers.get(f'no_tu3_{pegawai_id}') or doc_numbers.get('bapp') or ("1441/PN.01.02" if 'ASTIK' in kode_seksi else "1435/PN.01.02")
    no_ba_duk_1 = doc_numbers.get(f'no_tppbj1_{pegawai_id}') or doc_numbers.get('undangan') or (f"19/TPPBJ/KMFJP/{kode_seksi}/{prefix_sub}/{romawi}/{tahun_int}" if 'ASTIK' in kode_seksi else f"159/TPPBJ/KMFJP/ID/{prefix_sub}/{romawi}/{tahun_int}")
    no_ba_duk_2 = doc_numbers.get(f'no_tppbj2_{pegawai_id}') or doc_numbers.get('berita_acara_pemeriksaan') or (f"20/TPPBJ/KMFJP/{kode_seksi}/PJLP.KI/{romawi}/{tahun_int}" if 'ASTIK' in kode_seksi else f"160/TPPBJ/KMFJP/ID/{prefix_sub}/{romawi}/{tahun_int}")
    no_kwt = doc_numbers.get(f'no_kwt_{pegawai_id}') or doc_numbers.get('kwitansi') or f"88/KWT/{kode_seksi}/{prefix_sub}/XI/{tahun_int}"

    waktu_pemeriksaan = doc_numbers.get('waktu_pemeriksaan') or "16.30 s.d Selesai"
    hari_tgl_pemeriksaan = doc_numbers.get('hari_tanggal_pemeriksaan') or f"{hari_str}, {tanggal_pembuatan_bast}"

    replacements = {
        'No_Seksi_JKD': no_seksi_jkd,
        'Tanggal_Pembuatan_BAST': tanggal_pembuatan_bast,
        'Bulan_BAST': bulan_nama,
        'SPK_': spk_nomor,
        'Tanggal_SPK': spk_tgl,
        'No_TU_1': no_tu_1,
        'No_BA_Dukungan_Teknis_1': no_ba_duk_1,
        'HariTanggal_Pemeriksaan': hari_tgl_pemeriksaan,
        'Waktu_Pemeriksaan': waktu_pemeriksaan,
        'No_BA_Dukungan_Teknis_2': no_ba_duk_2,
        'Hari_Pembuatan_BAST': hari_str,
        'Penyebutan_Tanggal': penyebutan_tanggal,
        'Penyebutan_Bulan': penyebutan_bulan,
        'Nama_TA': nama_ta,
        'Gaji_1': format_rupiah_standard(gaji),
        'Gaji_2': format_rupiah_standard(gaji),
        'Terbilang_1': terbilang_1,
        'Terbilang_2': terbilang_2,
        'No_TU_2': no_tu_2,
        'Alamat': alamat_ta,
        'No_TU_3': no_tu_3,
        'No_Kwitansi': no_kwt,
        'TGL_SPK': spk_tgl.upper(),
        'ID_PHL': str(id_phl),
        'No_Rekening': str(no_rek),
        'NPWP': str(npwp),
        'Potongan_Absen': format_rupiah_standard(pot_absen),
        'Jumlah_Setelah_Potongan_Absen': format_rupiah_standard(set_pot),
        'BPJS_1': format_rupiah_standard(bpjs1),
        'PPH': format_rupiah_standard(pph),
        'Jumlah_Diterima': format_rupiah_standard(jumlah_diterima),
        'BPJS_4': format_rupiah_standard(bpjs4),
        'Nilai_Bruto': format_rupiah_standard(nilai_bruto),
        'BPJS_Ketenagakerjaan': format_rupiah_standard(bpjs_naker),
    }
    return replacements

def fill_document_xml(xml_content, replacements, doc_numbers=None, pegawai=None, pekerjaan=None):
    """
    1. Mengganti seluruh pola MERGEFIELD di OpenXML dengan nilai sebenarnya.
    2. Mengganti seluruh teks statis/berwarna (Red/Yellow/Blue) yang ada pada dokumen draft:
       - Nama Seksi & Singkatan
       - PPTK Nama, NIP, dan Jabatan
       - Program, Kegiatan, Sub Kegiatan, Aktivitas Sub Kegiatan, Kode Rekening
       - Nama Pekerjaan / Posisi
       - Tanggal Kwitansi, Waktu Pemeriksaan, Tempat Pemeriksaan
       - Pejabat PPK, Bendahara, Tim TPPBJ, dan SK TPPBJ
    """
    doc_numbers = doc_numbers or {}

    # LANGKAH 1: Ganti seluruh MERGEFIELD
    pattern = re.compile(
        r'(?s)(<w:r\b[^>]*>.*?<w:instrText[^>]*>\s*MERGEFIELD\s+"?([^"\s]+)"?\s*</w:instrText>.*?</w:r>'
        r'.*?<w:r\b[^>]*>.*?<w:fldChar\s+w:fldCharType="separate"/>.*?</w:r>'
        r'.*?<w:r\b[^>]*>(?:(?!<w:fldChar).)*?<w:t[^>]*>)'
        r'(.*?)'
        r'(</w:t>.*?</w:r>.*?<w:r\b[^>]*>.*?<w:fldChar\s+w:fldCharType="end"/>.*?</w:r>)'
    )

    def replace_match(match):
        prefix = match.group(1)
        field_name = match.group(2).strip()
        suffix = match.group(4)
        if field_name in replacements:
            val = escape_xml(replacements[field_name])
            return f"{prefix}{val}{suffix}"
        return match.group(0)

    xml_content = pattern.sub(replace_match, xml_content)

    # LANGKAH 2: Ganti teks dinamis non-MERGEFIELD (Warna Merah/Kuning/Biru pada Draft)

    # A. Nama Seksi & PPTK
    nama_seksi = doc_numbers.get('nama_seksi')
    if nama_seksi:
        # Jika nama seksi diawali kata "Seksi ", ambil bagian namanya saja untuk replace kata "Infrastruktur Digital"
        clean_seksi = re.sub(r'^Seksi\s+', '', nama_seksi).strip()
        xml_content = xml_content.replace('Infrastruktur Digital', escape_xml(clean_seksi))

    pptk_nama = doc_numbers.get('pptk_nama')
    if pptk_nama:
        xml_content = xml_content.replace('Yasri Rahman M.', escape_xml(pptk_nama))
        xml_content = xml_content.replace('Yasri Rahman M', escape_xml(pptk_nama))

    pptk_nip = doc_numbers.get('pptk_nip')
    if pptk_nip:
        xml_content = xml_content.replace('197808052011011008', escape_xml(pptk_nip))

    # B. Program, Kegiatan, Sub Kegiatan, Aktivitas Sub Kegiatan
    program = doc_numbers.get('program')
    if program:
        xml_content = xml_content.replace('Program Pengelolaan Aplikasi Informatika', escape_xml(program))

    kegiatan = doc_numbers.get('kegiatan')
    if kegiatan:
        xml_content = xml_content.replace('Pengelolaan E-government di Lingkup Pemerintah Daerah Provinsi', escape_xml(kegiatan))

    sub_kegiatan = doc_numbers.get('sub_kegiatan')
    if sub_kegiatan:
        xml_content = xml_content.replace('Penyelenggaraan Jaringan Intra Pemerintah Daerah Provinsi', escape_xml(sub_kegiatan))

    aktivitas = doc_numbers.get('aktivitas')
    if aktivitas:
        xml_content = xml_content.replace('PJLP Jaringan Intra Pemerintah Daerah', escape_xml(aktivitas))

    # C. Kode Rekening
    kode_rek = doc_numbers.get('kode_rekening')
    if kode_rek:
        xml_content = xml_content.replace('5.1.02.02.001.00039 Belanja Jasa Tenaga Informasi dan Teknologi', escape_xml(kode_rek))

    # D. Nama Pekerjaan / Posisi (Ganti "Petugas Informasi dan Teknologi – Teknisi Jaringan Senior Kominfotik" & "Pengadaan PJLP Jaringan Intra...")
    pekerjaan_nama = None
    if pegawai and pegawai.jabatan:
        pekerjaan_nama = pegawai.jabatan
    elif pekerjaan and pekerjaan.nama_pekerjaan:
        pekerjaan_nama = pekerjaan.nama_pekerjaan
    elif doc_numbers.get('nama_pekerjaan'):
        pekerjaan_nama = doc_numbers.get('nama_pekerjaan')

    if pekerjaan_nama:
        escaped_pek = escape_xml(pekerjaan_nama)
        # Ganti di run tabel dan tanda tangan
        xml_content = re.sub(
            r'(<w:t[^>]*>)\s*Petugas Informasi dan Teknologi\s*[^<]*?Teknisi Jaringan Senior Kominfotik\s*(</w:t>)',
            rf'\g<1>{escaped_pek}\g<2>',
            xml_content
        )
        xml_content = re.sub(
            r'(<w:t[^>]*>)\s*Teknisi Jaringan Senior Kominfotik\s*(</w:t>)',
            rf'\g<1>{escaped_pek}\g<2>',
            xml_content
        )
        # Ganti "Pengadaan PJLP Jaringan Intra Pemerintah Daerah"
        xml_content = xml_content.replace('Pengadaan PJLP Jaringan Intra Pemerintah Daerah', escaped_pek)

    # E. Tanggal Kwitansi & Jadwal Pemeriksaan
    tgl_kwitansi = doc_numbers.get('tanggal_kwitansi')
    if tgl_kwitansi:
        xml_content = xml_content.replace('02 November 2026', escape_xml(tgl_kwitansi))

    waktu_pem = doc_numbers.get('waktu_pemeriksaan')
    if waktu_pem:
        xml_content = xml_content.replace('16.30 s.d Selesai', escape_xml(waktu_pem))

    tempat_pem = doc_numbers.get('tempat_pemeriksaan')
    if tempat_pem:
        xml_content = xml_content.replace('Sudin Kominfotik Kota Administrasi Jakarta Pusat', escape_xml(tempat_pem))

    # F. Data Pejabat Penandatangan Lainnya (PPK, Bendahara, Tim TPPBJ)
    if doc_numbers.get('ppk_nama'):
        xml_content = xml_content.replace('Rachmat Setiawan', escape_xml(doc_numbers['ppk_nama']))
    if doc_numbers.get('ppk_nip'):
        xml_content = xml_content.replace('198102022006041009', escape_xml(doc_numbers['ppk_nip']))

    if doc_numbers.get('bendahara_nama'):
        xml_content = xml_content.replace('Roslaini Harahap', escape_xml(doc_numbers['bendahara_nama']))
    if doc_numbers.get('bendahara_nip'):
        xml_content = xml_content.replace('197203121993032007', escape_xml(doc_numbers['bendahara_nip']))

    # Jabatan penandatangan (hanya diganti bila berbeda dari teks bawaan dokumen)
    jab_ppk = (doc_numbers.get('ppk_jabatan') or '').strip()
    if jab_ppk and jab_ppk != 'Pejabat Pembuat Komitmen':
        xml_content = xml_content.replace('Pejabat Pembuat Komitmen', escape_xml(jab_ppk))

    jab_pptk = (doc_numbers.get('pptk_jabatan_ttd') or '').strip()
    if jab_pptk and jab_pptk != 'Pejabat Pelaksana Teknis Kegiatan':
        xml_content = re.sub(
            r'(<w:t[^>]*>)Pejabat Pelaksana Teknis Kegiatan(</w:t>)',
            lambda m: m.group(1) + escape_xml(jab_pptk) + m.group(2),
            xml_content)

    jab_bend = (doc_numbers.get('bendahara_jabatan') or '').strip()
    if jab_bend and jab_bend.replace(' ', '') != 'BendaharaPengeluaran/PengeluaranPembantu':
        xml_content = re.sub(r'(<w:t[^>]*>)\s*Pengeluaran Pembantu\s*(</w:t>)', r'\g<1>\g<2>', xml_content)
        xml_content = xml_content.replace('Bendahara Pengeluaran/', escape_xml(jab_bend))

    if doc_numbers.get('tppbj_ketua'):
        xml_content = xml_content.replace('Eka Novia Gunawan', escape_xml(doc_numbers['tppbj_ketua']))
    if doc_numbers.get('tppbj_ketua_nip'):
        xml_content = xml_content.replace('198011082011011007', escape_xml(doc_numbers['tppbj_ketua_nip']))

    if doc_numbers.get('tppbj_sekretaris'):
        xml_content = xml_content.replace('Reza Ayatuna Lazuardy', escape_xml(doc_numbers['tppbj_sekretaris']))

    if doc_numbers.get('tppbj_anggota'):
        xml_content = xml_content.replace('Sulaeman', escape_xml(doc_numbers['tppbj_anggota']))

    if doc_numbers.get('sk_tppbj'):
        xml_content = xml_content.replace('03 Tahun 2026', escape_xml(doc_numbers['sk_tppbj']))

    return xml_content

def _png_ratio(data):
    """Rasio lebar/tinggi PNG (tanpa Pillow). Default 2.5 bila bukan PNG."""
    import struct
    try:
        if data[:8] == b'\x89PNG\r\n\x1a\n':
            w, h = struct.unpack('>II', data[16:24])
            if w > 0 and h > 0:
                return w / h
    except Exception:
        pass
    return 2.5


def make_anchor_run(r_id, doc_pr_id, name, ratio, height=520000, width_max=1500000):
    """
    Gambar tanda tangan MENGAMBANG (anchor, wrapNone, di belakang teks) sehingga
    TIDAK menambah tinggi baris/paragraf -> tata letak dokumen tidak bergeser.
    Posisi: rata tengah kolom, bagian bawah gambar menempel di atas nama penandatangan.
    """
    cy = height
    cx = int(cy * ratio)
    if cx > width_max:
        cx = width_max
        cy = int(cx / ratio)
    off_v = -cy + 60000
    nm = escape_xml(name)
    return (
        '<w:r><w:drawing>'
        '<wp:anchor distT="0" distB="0" distL="0" distR="0" simplePos="0" relativeHeight="251700000" '
        'behindDoc="1" locked="0" layoutInCell="1" allowOverlap="1">'
        '<wp:simplePos x="0" y="0"/>'
        '<wp:positionH relativeFrom="column"><wp:align>center</wp:align></wp:positionH>'
        f'<wp:positionV relativeFrom="paragraph"><wp:posOffset>{off_v}</wp:posOffset></wp:positionV>'
        f'<wp:extent cx="{cx}" cy="{cy}"/>'
        '<wp:effectExtent l="0" t="0" r="0" b="0"/>'
        '<wp:wrapNone/>'
        f'<wp:docPr id="{doc_pr_id}" name="{nm}"/>'
        '<wp:cNvGraphicFramePr><a:graphicFrameLocks xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main" noChangeAspect="1"/></wp:cNvGraphicFramePr>'
        '<a:graphic xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main">'
        '<a:graphicData uri="http://schemas.openxmlformats.org/drawingml/2006/picture">'
        '<pic:pic xmlns:pic="http://schemas.openxmlformats.org/drawingml/2006/picture">'
        f'<pic:nvPicPr><pic:cNvPr id="0" name="{nm}.png"/><pic:cNvPicPr/></pic:nvPicPr>'
        f'<pic:blipFill><a:blip r:embed="{r_id}"/><a:stretch><a:fillRect/></a:stretch></pic:blipFill>'
        f'<pic:spPr><a:xfrm><a:off x="0" y="0"/><a:ext cx="{cx}" cy="{cy}"/></a:xfrm>'
        '<a:prstGeom prst="rect"><a:avLst/></a:prstGeom></pic:spPr>'
        '</pic:pic></a:graphicData></a:graphic></wp:anchor></w:drawing></w:r>'
    )


_P_TEXT = re.compile(r'<w:t[^>]*>(.*?)</w:t>', re.S)
_uid = [0]


def embed_signature_anchor(xml, name_regex, name_len, run_xml):
    """
    Cari paragraf yang HANYA berisi nama penandatangan (bukan baris label),
    lalu tempelkan gambar mengambang ke paragraf kosong tepat di atasnya.
    Jumlah paragraf tidak berubah.
    """
    pat = re.compile(
        r'(<w:p\b[^>]*>(?:(?!<w:t[ >]|</w:p>).)*?)(</w:p>)'
        r'(\s*<w:p\b[^>]*>(?:(?!</w:p>).)*?' + name_regex + r'.*?</w:p>)',
        re.S)

    def repl(m):
        name_p = m.group(3)
        text = ''.join(_P_TEXT.findall(name_p)).strip()
        if len(text) > name_len + 3:
            return m.group(0)
        _uid[0] += 1
        unique_run = re.sub(r'(<wp:docPr id=")\d+(")', lambda mm: f'{mm.group(1)}{9000 + _uid[0]}{mm.group(2)}', run_xml)
        return m.group(1) + unique_run + m.group(2) + name_p

    return pat.sub(repl, xml)




def generate_exact_word_docx(laporan, pegawai, pembayaran=None, pekerjaan=None, doc_numbers=None):
    """
    Menghasilkan file DOCX lengkap untuk seorang pegawai berdasarkan contoh_laporan.docx.
    Hasilnya dijamin SAMA PERSIS dengan dokumen resmi kedinasan.
    Tanda tangan digital (jika ada) akan disisipkan otomatis; jika tidak ada,
    dokumen TETAP berhasil diunduh dengan format tanda tangan standar (kosong).
    """
    if not os.path.exists(TEMPLATE_PATH):
        raise FileNotFoundError(f"Template dokumen tidak ditemukan di {TEMPLATE_PATH}")

    replacements = build_merge_replacements(
        laporan=laporan,
        pegawai=pegawai,
        pembayaran=pembayaran,
        pekerjaan=pekerjaan,
        doc_numbers=doc_numbers
    )

    # Ambil tanda tangan digital dari database (jika ada)
    from . import signatures as ttd_store
    signatures_to_embed = {}
    kandidat = []
    if pegawai:
        kandidat.append(('rIdSigPegawai', f'pegawai_{pegawai.id}.png', f'sig_pegawai_{pegawai.id}.png', f'TTD_{pegawai.nama}'))
    kandidat += [
        ('rIdSigPPTK', 'pejabat_pptk.png', 'sig_pejabat_pptk.png', 'TTD_PPTK'),
        ('rIdSigPPK', 'pejabat_ppk.png', 'sig_pejabat_ppk.png', 'TTD_PPK'),
        ('rIdSigBendahara', 'pejabat_bendahara.png', 'sig_pejabat_bendahara.png', 'TTD_Bendahara'),
    ]
    for rid, sumber, target, nama in kandidat:
        try:
            data = ttd_store.ambil(sumber)
        except Exception:
            data = None
        if data:
            signatures_to_embed[rid] = {'filename': target, 'bytes': data, 'name': nama}

    output_buffer = io.BytesIO()

    with zipfile.ZipFile(TEMPLATE_PATH, 'r') as src_zip:
        with zipfile.ZipFile(output_buffer, 'w', compression=zipfile.ZIP_DEFLATED) as dst_zip:
            for item in src_zip.infolist():
                content = src_zip.read(item.filename)

                # 1. Update rels jika ada tanda tangan digital yang perlu disematkan
                if item.filename == 'word/_rels/document.xml.rels' and signatures_to_embed:
                    rels_str = content.decode('utf-8')
                    extra_rels = ""
                    for r_id, info in signatures_to_embed.items():
                        extra_rels += f'<Relationship Id="{r_id}" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/image" Target="media/{info["filename"]}"/>'
                    rels_str = rels_str.replace('</Relationships>', f'{extra_rels}</Relationships>')
                    dst_zip.writestr(item, rels_str.encode('utf-8'))

                # 2. Sisipkan tanda tangan & isi seluruh variabel ke word/document.xml
                elif item.filename == 'word/document.xml':
                    xml_str = content.decode('utf-8')

                    # Tempel gambar tanda tangan mengambang (tidak menggeser tata letak)
                    targets = [
                        ('rIdSigPegawai', 9001, r'MERGEFIELD\s+"?Nama_TA"?', len('Faris Ibnu Hasan')),
                        ('rIdSigPPTK', 9002, r'Yasri Rahman M', len('Yasri Rahman M.')),
                        ('rIdSigPPK', 9003, r'Rachmat Setiawan', len('Rachmat Setiawan')),
                        ('rIdSigBendahara', 9004, r'Roslaini', len('Roslaini Harahap')),
                    ]
                    for rid, did, rx, ln in targets:
                        if rid in signatures_to_embed:
                            info = signatures_to_embed[rid]
                            run_xml = make_anchor_run(rid, did, info['name'], _png_ratio(info['bytes']))
                            xml_str = embed_signature_anchor(xml_str, rx, ln, run_xml)

                    modified_xml = fill_document_xml(
                        xml_content=xml_str,
                        replacements=replacements,
                        doc_numbers=doc_numbers,
                        pegawai=pegawai,
                        pekerjaan=pekerjaan
                    )
                    dst_zip.writestr(item, modified_xml.encode('utf-8'))
                else:
                    dst_zip.writestr(item, content)

            # Tambahkan berkas-berkas gambar tanda tangan ke dalam arsip docx
            for r_id, info in signatures_to_embed.items():
                dst_zip.writestr(f"word/media/{info['filename']}", info['bytes'])

    output_buffer.seek(0)
    return output_buffer

def generate_all_pegawai_zip(laporan, pembayaran_list, pekerjaan=None, doc_numbers=None):
    """
    Membuat file ZIP yang memuat seluruh dokumen Word untuk setiap pegawai dalam laporan.
    """
    zip_buffer = io.BytesIO()
    with zipfile.ZipFile(zip_buffer, 'w', compression=zipfile.ZIP_DEFLATED) as out_zip:
        for idx, pb in enumerate(pembayaran_list, start=1):
            peg = pb.pegawai
            if not peg:
                continue
            docx_buf = generate_exact_word_docx(
                laporan=laporan,
                pegawai=peg,
                pembayaran=pb,
                pekerjaan=pekerjaan,
                doc_numbers=doc_numbers
            )
            safe_name = re.sub(r'[^a-zA-Z0-9_\- ]', '', peg.nama).strip().replace(' ', '_')
            filename = f"{idx:02d}_{safe_name}_Laporan_{NAMA_BULAN.get(laporan.bulan, laporan.bulan)}_{laporan.tahun}.docx"
            out_zip.writestr(filename, docx_buf.getvalue())

    zip_buffer.seek(0)
    return zip_buffer
