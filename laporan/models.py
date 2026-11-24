
from django.db import models


class LaporanBulanan(models.Model):
    id = models.BigAutoField(primary_key=True)
    bulan = models.PositiveSmallIntegerField()
    tahun = models.PositiveSmallIntegerField()
    tanggal_mulai = models.DateField(blank=True, null=True)
    tanggal_selesai = models.DateField(blank=True, null=True)
    status = models.CharField(
        max_length=7,
        choices=[
            ('draft', 'Draft'),
            ('selesai', 'Selesai'),
        ],
        default='draft',
        blank=True,
        null=True
    )
    created_at = models.DateTimeField()

    class Meta:
        db_table = 'laporan_bulanan'


class NomorDokumen(models.Model):
    id = models.BigAutoField(primary_key=True)
    laporan = models.ForeignKey(
        LaporanBulanan,
        models.DO_NOTHING,
        db_column='laporan_id'
    )
    jenis_dokumen = models.CharField(max_length=100)
    nomor_surat = models.CharField(max_length=150)
    tanggal_surat = models.DateField(blank=True, null=True)

    class Meta:
        db_table = 'nomor_dokumen'


class Pegawai(models.Model):
    id = models.BigAutoField(primary_key=True)
    id_phl = models.CharField(
        max_length=30,
        blank=True,
        null=True
    )
    nama = models.CharField(max_length=150)
    jabatan = models.CharField(max_length=100, blank=True, null=True)
    nip = models.CharField(max_length=50, blank=True, null=True)
    npwp = models.CharField(max_length=50, blank=True, null=True)
    nomor_rekening = models.CharField(
        max_length=50,
        blank=True,
        null=True
    )
    alamat = models.TextField(blank=True, null=True)

    class Meta:
        db_table = 'pegawai'


class Pekerjaan(models.Model):
    id = models.BigAutoField(primary_key=True)
    laporan = models.ForeignKey(
        LaporanBulanan,
        models.DO_NOTHING,
        db_column='laporan_id'
    )
    nama_pekerjaan = models.CharField(max_length=255)
    nomor_spk = models.CharField(max_length=100, blank=True, null=True)
    tanggal_spk = models.DateField(blank=True, null=True)
    volume = models.CharField(max_length=100, blank=True, null=True)
    keterangan = models.TextField(blank=True, null=True)

    class Meta:
        db_table = 'pekerjaan'


class Pembayaran(models.Model):
    id = models.BigAutoField(primary_key=True)
    laporan = models.ForeignKey(
        LaporanBulanan,
        models.DO_NOTHING,
        db_column='laporan_id'
    )
    pegawai = models.ForeignKey(
        Pegawai,
        models.DO_NOTHING,
        db_column='pegawai_id'
    )
    honorarium = models.DecimalField(
        max_digits=15,
        decimal_places=2,
        blank=True,
        null=True
    )
    potongan_kehadiran = models.DecimalField(
        max_digits=15,
        decimal_places=2,
        blank=True,
        null=True
    )
    jumlah_setelah_potongan_absen = models.DecimalField(
        max_digits=15,
        decimal_places=2,
        blank=True,
        null=True,
        default=0
    )
    bpjs = models.DecimalField(
        max_digits=15,
        decimal_places=2,
        blank=True,
        null=True
    )
    pph21 = models.DecimalField(
        max_digits=15,
        decimal_places=2,
        blank=True,
        null=True
    )
    bpjs_pemberi_kerja = models.DecimalField(
        max_digits=15,
        decimal_places=2,
        blank=True,
        null=True
    )
    nilai_bruto = models.DecimalField(
        max_digits=15,
        decimal_places=2,
        blank=True,
        null=True,
        default=0
    )
    bpjs_ketenagakerjaan = models.DecimalField(
        max_digits=15,
        decimal_places=2,
        blank=True,
        null=True,
        default=0
    )
    total_diterima = models.DecimalField(
        max_digits=15,
        decimal_places=2,
        blank=True,
        null=True
    )

    class Meta:
        db_table = 'pembayaran'


class Pemeriksaan(models.Model):
    id = models.BigAutoField(primary_key=True)
    pekerjaan = models.ForeignKey(
        Pekerjaan,
        models.DO_NOTHING,
        db_column='pekerjaan_id'
    )
    jenis_pemeriksaan = models.CharField(
        max_length=100,
        blank=True,
        null=True
    )
    nomor_dokumen = models.CharField(
        max_length=100,
        blank=True,
        null=True
    )
    tanggal = models.DateField(blank=True, null=True)
    hasil = models.TextField(blank=True, null=True)
    keterangan = models.TextField(blank=True, null=True)

    class Meta:
        db_table = 'pemeriksaan'


class Penugasan(models.Model):
    id = models.BigAutoField(primary_key=True)
    laporan = models.ForeignKey(
        LaporanBulanan,
        models.DO_NOTHING,
        db_column='laporan_id'
    )
    pegawai = models.ForeignKey(
        Pegawai,
        models.DO_NOTHING,
        db_column='pegawai_id'
    )
    peran = models.CharField(max_length=100)

    class Meta:
        db_table = 'penugasan'


class StokBulanan(models.Model):
    id = models.BigAutoField(primary_key=True)
    laporan = models.ForeignKey(
        LaporanBulanan,
        models.DO_NOTHING,
        db_column='laporan_id'
    )
    nama_barang = models.CharField(max_length=150)
    stok_awal = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        blank=True,
        null=True
    )
    barang_masuk = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        blank=True,
        null=True
    )
    barang_keluar = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        blank=True,
        null=True
    )
    stok_akhir = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        blank=True,
        null=True
    )
    satuan = models.CharField(max_length=30, blank=True, null=True)

    class Meta:
        db_table = 'stok_bulanan'


class TandaTangan(models.Model):
    """Tanda tangan digital (PNG) disimpan di database agar tidak bergantung pada disk server."""
    nama_berkas = models.CharField(max_length=100, unique=True)
    data = models.BinaryField()
    diperbarui = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'tanda_tangan'

    def __str__(self):
        return self.nama_berkas


class Pejabat(models.Model):
    """
    Data Master Pejabat Penandatangan Kedinasan.
    Mendukung opsi pemilihan tanda tangan digital berurutan dari kiri ke kanan.
    """
    POSISI_PILIHAN = [
        ('kiri', 'Kolom Kiri (Pihak Pertama / Pelaksana / PPTK)'),
        ('tengah', 'Kolom Tengah (Mengetahui / PPK)'),
        ('kanan', 'Kolom Kanan (Pihak Kedua / Bendahara / Kasudin)'),
    ]

    id = models.BigAutoField(primary_key=True)
    nama = models.CharField(max_length=150)
    nip = models.CharField(max_length=50, blank=True, null=True)
    jabatan = models.CharField(max_length=200, blank=True, null=True)
    peran = models.CharField(max_length=50, blank=True, null=True, help_text="Kode peran, cth: pptk, ppk, bendahara, kasudin")
    urutan = models.PositiveSmallIntegerField(default=1, help_text="Urutan posisi tanda tangan: 1 (kiri), 2 (tengah), 3 (kanan), dst.")
    posisi_kolom = models.CharField(max_length=20, default='kiri', choices=POSISI_PILIHAN)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'pejabat'
        ordering = ['urutan', 'id']

    def __str__(self):
        return f"{self.nama} ({self.jabatan or self.peran or 'Pejabat'})"

    @property
    def file_ttd(self):
        """Nama berkas tanda tangan pejabat untuk pencocokan di tabel TandaTangan."""
        if self.peran:
            return f"pejabat_{self.peran.lower().strip()}.png"
        return f"pejabat_id_{self.id}.png"

