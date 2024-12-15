import io
import logging
import os
import sys
from io import BytesIO
from pathlib import Path
from threading import Thread
from unittest.mock import call, patch

import fpdf
import pytest
from PIL import Image, ImageDraw, ImageFont, TiffImagePlugin
from PyPDF2 import PdfReader, PdfWriter
from fpdf import FPDF
from fpdf.image_parsing import transcode_monochrome

from test.conftest import assert_pdf_equal

HERE = Path(__file__).resolve().parent


def test_fillorder_lsb_to_msb():
    img_data = BytesIO()
    img = Image.new("1", (10, 10), 0)
    img.save(
        img_data,
        format="TIFF",
        compression="group4",
        tiffinfo={TiffImagePlugin.FILLORDER: 2},
    )
    img_data.seek(0)

    with Image.open(img_data) as test_img:
        filename = "test.tiff"

        with patch(
            "fpdf.image_parsing.get_img_info",
            return_value={
                "f": "CCITTFaxDecode",
                "cs": "DeviceGray",
                "data": b"test_bytes",
            },
        ) as mock_get_img_info:
            result = mock_get_img_info(
                filename, test_img, image_filter="CCITTFaxDecode"
            )

            assert result["f"] == "CCITTFaxDecode"
            assert result["cs"] == "DeviceGray"
            assert isinstance(result["data"], bytes)
            mock_get_img_info.assert_called_once_with(
                filename, test_img, image_filter="CCITTFaxDecode"
            )


def test_generate_multitable_pdf_with_mock():
    class PDFWithTable(FPDF):
        def header(self):
            self.set_font("Arial", "B", 12)
            self.cell(0, 10, "Test Header", align="C", ln=1)

        def add_table(self, data):
            self.set_font("Arial", size=10)
            col_width = 40
            row_height = 10

            for row in data:
                for item in row:
                    self.cell(col_width, row_height, item, border=1)
                self.ln(row_height)

        def add_image(self, image_path, x, y, w, h):
            self.image(image_path, x=x, y=y, w=w, h=h)

    pdf = PDFWithTable()

    table_data = [
        ["Header1", "Header2", "Header3"],
        ["Row1Col1", "Row1Col2", "Row1Col3"],
        ["Row2Col1", "Row2Col2", "Row2Col3"],
        ["Row3Col1", "Row3Col2", "Row3Col3"],
    ]

    with patch.object(pdf, "cell") as mock_cell, patch.object(
        pdf, "ln"
    ) as mock_ln, patch.object(pdf, "image") as mock_image:
        pdf.add_page()
        pdf.add_table(table_data)

        pdf.add_image(HERE / "pythonknight.png", x=10, y=100, w=50, h=50)

        table_cell_calls = [
            call(40, 10, "Header1", border=1),
            call(40, 10, "Header2", border=1),
            call(40, 10, "Header3", border=1),
            call(40, 10, "Row1Col1", border=1),
            call(40, 10, "Row1Col2", border=1),
            call(40, 10, "Row1Col3", border=1),
            call(40, 10, "Row2Col1", border=1),
            call(40, 10, "Row2Col2", border=1),
            call(40, 10, "Row2Col3", border=1),
            call(40, 10, "Row3Col1", border=1),
            call(40, 10, "Row3Col2", border=1),
            call(40, 10, "Row3Col3", border=1),
        ]

        mock_cell.assert_has_calls(table_cell_calls, any_order=False)

        expected_ln_calls = [call(10)] * len(table_data)
        mock_ln.assert_has_calls(expected_ln_calls, any_order=False)

        mock_image.assert_called_once_with(
            HERE / "pythonknight.png", x=10, y=100, w=50, h=50
        )

        table_cells_count = len(table_data) * len(table_data[0])
        assert mock_cell.call_count == table_cells_count + 1
        assert mock_ln.call_count == len(table_data)

    assert len(pdf.pages) == 1


def test_broken_image():
    broken_image = BytesIO(b"not_an_image")

    with patch.object(
        FPDF, "image", side_effect=RuntimeError("Unsupported image format")
    ):
        pdf = FPDF()
        pdf.add_page()

        with pytest.raises(RuntimeError, match="Unsupported image format"):
            pdf.image(broken_image, x=10, y=10, w=50, h=50)


def test_large_table():
    pdf = FPDF()
    pdf.add_page()
    pdf.set_font("Arial", size=10)

    for i in range(10000):
        pdf.cell(40, 10, f"Row {i}", border=1)
        pdf.cell(40, 10, "Data", border=1)
        pdf.cell(40, 10, "More Data", border=1)
        pdf.ln()

    pdf_file_path = "test_large_table.pdf"
    pdf.output(pdf_file_path)
    fake_file = BytesIO()
    pdf.output(fake_file)
    fake_file.seek(0)

    reader = PdfReader(fake_file)
    text = ""
    for page in reader.pages:
        text += page.extract_text()

    assert "Row 999" in text, "Row 999 not found in extracted text"

    with open("test_large_table.pdf", "wb") as f:
        f.write(fake_file.getvalue())

    print("Test passed and PDF saved as 'test_large_table.pdf'")


def test_unsupported_font_error():
    pdf = FPDF()
    pdf.add_page()

    with pytest.raises(
        FileNotFoundError, match="TTF Font file not found: nonexistent.ttf"
    ):
        pdf.add_font("NonExistentFont", "", "nonexistent.ttf", uni=True)


def test_long_text_wrapping():
    pdf = FPDF()
    pdf.add_page()
    long_text = (
        "This is a very long sentence that will hopefully wrap onto the next line."
    )
    pdf.set_font("Arial", size=12)
    pdf.multi_cell(0, 10, long_text)

    fake_file = BytesIO()
    pdf.output(fake_file)
    fake_file.seek(0)

    reader = PdfReader(fake_file)
    text = ""
    for page in reader.pages:
        text += page.extract_text()

    assert "This is a very long sentence" in text


def test_extreme_page_size():
    pdf = FPDF()

    extreme_size = (9999999, 9999999)

    try:
        pdf.add_page(orientation="P", format=extreme_size)
        pdf.set_font("Arial", size=12)
        pdf.cell(0, 10, "Extreme Page Size Test", ln=True)

        fake_file = BytesIO()
        pdf.output(fake_file)
        fake_file.seek(0)

        reader = PdfReader(fake_file)
        text = ""
        for page in reader.pages:
            text += page.extract_text()

        assert "Extreme Page Size Test" in text

    except (RuntimeError, ValueError, OSError) as e:
        pytest.fail(f"Test failed due to an exception: {str(e)}")


def test_extreme_page_size_create():
    pdf = FPDF()

    extreme_size = (9999999, 9999999)

    pdf.add_page(orientation="P", format=extreme_size)
    pdf.set_font("Arial", size=12)
    pdf.cell(0, 10, "Extreme Page Size Test", ln=True)

    output_file = "test_extreme_page_size.pdf"
    pdf.output(output_file)

    assert os.path.exists(output_file), "PDF doesnt crate"

    file_size = os.path.getsize(output_file)
    assert file_size > 0, "PDF file is empty"

    os.remove(output_file)


def test_parallel_element_addition():
    pdf = FPDF()
    pdf.add_page()
    pdf.set_font("Arial", size=12)

    def add_cells():
        for i in range(100):
            pdf.cell(40, 10, f"Thread Row {i}", border=1)

    threads = [Thread(target=add_cells) for _ in range(5)]

    for thread in threads:
        thread.start()

    for thread in threads:
        thread.join()

    fake_file = BytesIO()
    pdf.output(fake_file)
    fake_file.seek(0)

    reader = PdfReader(fake_file)
    text = "".join(page.extract_text() for page in reader.pages)

    assert "Thread Row 99" in text, "Last row from threads not found in PDF"


def test_password_protected_pdf():
    # Step 1: Create PDF with FPDF
    pdf = FPDF()
    pdf.add_page()
    pdf.set_font("Arial", size=12)
    pdf.cell(0, 10, "This is a password-protected PDF.", ln=True)

    fake_file = BytesIO()
    pdf.output(fake_file)
    fake_file.seek(0)

    # Step 2: Protect PDF with PyPDF2
    writer = PdfWriter()
    reader = PdfReader(fake_file)

    for page in reader.pages:
        writer.add_page(page)

    writer.encrypt(user_password="userpass", owner_password="ownerpass")
    protected_file = BytesIO()
    writer.write(protected_file)
    protected_file.seek(0)

    # Step 3: Try to modify PDF with FPDF
    protected_reader = PdfReader(protected_file)

    with pytest.raises(Exception, match="File has not been decrypted"):
        _ = protected_reader.pages[0].extract_text()  # pylint: disable=no-member

    protected_reader.decrypt("userpass")
    text = protected_reader.pages[0].extract_text()  # pylint: disable=no-member

    assert "This is a password-protected PDF." in text

    # Attempting to add content to a protected PDF with FPDF
    new_pdf = FPDF()
    new_pdf.add_page()
    new_pdf.set_font("Arial", size=12)
    new_pdf.cell(0, 10, "Trying to modify a protected PDF.", ln=True)

    modified_file = BytesIO()
    new_pdf.output(modified_file)
    modified_file.seek(0)

    assert (
        modified_file.getvalue() != protected_file.getvalue()
    ), "Modification should not affect the protected PDF."


def test_insert_jpg(tmp_path):
    pdf = fpdf.FPDF()
    pdf.compress = False
    pdf.add_page()
    pdf.image(HERE / "insert_images_insert_jpg.jpg", x=15, y=15, h=140)
    assert_pdf_equal(pdf, HERE / "image_types_insert_jpg.pdf", tmp_path)


@pytest.mark.skipif(
    sys.platform in ("cygwin", "win32"),
    reason="Required system libraries to generate JPEG2000 images are a PITA to install under Windows",
)
def test_insert_jpg_jpxdecode(tmp_path):
    pdf = fpdf.FPDF()
    pdf.compress = False
    pdf.set_image_filter("JPXDecode")
    pdf.add_page()
    pdf.image(HERE / "insert_images_insert_jpg.jpg", x=15, y=15, h=140)
    assert_pdf_equal(pdf, HERE / "image_types_insert_jpg_jpxdecode.pdf", tmp_path)


def test_insert_jpg_flatedecode(tmp_path):
    pdf = fpdf.FPDF()
    pdf.compress = False
    pdf.set_image_filter("FlateDecode")
    pdf.add_page()
    pdf.image(HERE / "insert_images_insert_jpg.jpg", x=15, y=15, h=140)
    if sys.platform in ("cygwin", "win32"):
        # Pillow uses libjpeg-turbo on Windows and libjpeg elsewhere,
        # leading to a slightly different image being parsed and included in the PDF:
        assert_pdf_equal(
            pdf, HERE / "image_types_insert_jpg_flatedecode_windows.pdf", tmp_path
        )
    else:
        assert_pdf_equal(pdf, HERE / "image_types_insert_jpg_flatedecode.pdf", tmp_path)


def test_insert_jpg_lzwdecode(tmp_path):
    pdf = fpdf.FPDF()
    pdf.compress = False
    pdf.set_image_filter("LZWDecode")
    pdf.add_page()
    pdf.image(HERE / "insert_images_insert_jpg.jpg", x=15, y=15, h=140)
    if sys.platform in ("cygwin", "win32"):
        assert_pdf_equal(
            pdf,
            HERE / "image_types_insert_jpg_lzwdecode_windows.pdf",
            tmp_path,
        )
    else:
        assert_pdf_equal(
            pdf,
            HERE / "image_types_insert_jpg_lzwdecode.pdf",
            tmp_path,
        )


def test_insert_jpg_cmyk(tmp_path):
    pdf = fpdf.FPDF()
    pdf.compress = False
    pdf.add_page()
    pdf.image(HERE / "insert_images_insert_jpg_cmyk.jpg", x=15, y=15)
    assert_pdf_equal(pdf, HERE / "images_types_insert_jpg_cmyk.pdf", tmp_path)


def test_insert_png(tmp_path):
    pdf = fpdf.FPDF()
    pdf.add_page()
    pdf.image(HERE / "insert_images_insert_png.png", x=15, y=15, h=140)
    assert_pdf_equal(pdf, HERE / "image_types_insert_png.pdf", tmp_path)


def test_insert_png_monochromatic(tmp_path):
    pdf = fpdf.FPDF()
    pdf.add_page()
    pdf.image(HERE / "../png_test_suite/basi0g01.png", x=15, y=15, h=140)
    assert_pdf_equal(pdf, HERE / "image_types_insert_png_monochromatic.pdf", tmp_path)


def test_transcode_monochrome_and_libtiff_support_custom_tags():
    # Fails under WSL on my computer (Lucas), with this error:
    #   AttributeError: module 'PIL._imaging' has no attribute 'libtiff_support_custom_tags'
    # (as a consequence, the test above & everal others also fail, because PDFs don't match)
    # cf. https://github.com/python-pillow/Pillow/issues/7019
    with Image.open("test/image/png_test_suite/basi0g01.png") as img:
        transcode_monochrome(img)


def test_insert_png_alpha(tmp_path):
    pdf = fpdf.FPDF()
    pdf.compress = False
    pdf.add_page()
    pdf.set_font("Helvetica", size=30)
    pdf.cell(w=pdf.epw, h=30, text="BEHIND")
    pdf.image(
        HERE / "../png_images/ba2b2b6e72ca0e4683bb640e2d5572f8.png", x=25, y=0, h=40
    )
    assert_pdf_equal(pdf, HERE / "image_types_insert_png_alpha.pdf", tmp_path)


def test_insert_png_disallow_transparency(tmp_path):
    pdf = fpdf.FPDF()
    pdf.allow_images_transparency = False
    pdf.add_page()
    pdf.set_font("Helvetica", size=30)
    pdf.cell(w=pdf.epw, h=30, text="BEHIND")
    pdf.image(
        HERE / "../png_images/ba2b2b6e72ca0e4683bb640e2d5572f8.png", x=25, y=0, h=40
    )
    assert_pdf_equal(
        pdf, HERE / "image_types_insert_png_disallow_transparency.pdf", tmp_path
    )


def test_insert_png_alpha_dctdecode(tmp_path):
    pdf = fpdf.FPDF()
    pdf.compress = False
    pdf.set_image_filter("DCTDecode")
    pdf.add_page()
    pdf.image(
        HERE / "../png_images/ba2b2b6e72ca0e4683bb640e2d5572f8.png", x=15, y=15, h=140
    )
    if sys.platform in ("cygwin", "win32"):
        # Pillow uses libjpeg-turbo on Windows and libjpeg elsewhere,
        # leading to a slightly different image being parsed and included in the PDF:
        assert_pdf_equal(
            pdf, HERE / "image_types_insert_png_alpha_dctdecode_windows.pdf", tmp_path
        )
    else:
        assert_pdf_equal(
            pdf, HERE / "image_types_insert_png_alpha_dctdecode.pdf", tmp_path
        )


def test_insert_bmp(tmp_path):
    pdf = fpdf.FPDF()
    pdf.compress = False
    pdf.add_page()
    pdf.image(HERE / "circle.bmp", x=15, y=15, h=140)
    assert_pdf_equal(pdf, HERE / "image_types_insert_bmp.pdf", tmp_path)


def test_insert_jpg_icc(tmp_path):
    pdf = fpdf.FPDF()
    pdf.add_page(format=(448, 498))
    pdf.set_margin(0)
    pdf.image(HERE / "insert_images_insert_jpg_icc.jpg", x=0, y=0, h=498)
    # we add the same image a second time to make sure the ICC profile is only included
    # only once in that case
    pdf.add_page(format=(448, 498))
    pdf.image(HERE / "insert_images_insert_jpg_icc.jpg", x=0, y=0, h=498)
    # we add another image with the same ICC profile to make sure it's also included
    # only once in that case
    pdf.add_page(format=(314, 500))
    pdf.image(HERE / "insert_images_insert_jpg_icc_2.jpg", x=0, y=0, h=500)
    assert_pdf_equal(pdf, HERE / "image_types_insert_jpg_icc.pdf", tmp_path)


def test_insert_jpg_invalid_icc(caplog, tmp_path):
    with caplog.at_level(logging.INFO):
        pdf = fpdf.FPDF()
        pdf.add_page(format=(448, 498))
        pdf.set_margin(0)
        pdf.image(HERE / "insert_images_insert_jpg_icc_invalid.jpg", x=0, y=0, h=498)
    assert "Invalid ICC Profile in file" in caplog.text
    assert_pdf_equal(pdf, HERE / "image_types_insert_jpg_icc_invalid.pdf", tmp_path)


def test_insert_gif(tmp_path):
    pdf = fpdf.FPDF()
    pdf.compress = False
    pdf.add_page()
    pdf.image(HERE / "circle.gif", x=15, y=15)
    assert_pdf_equal(pdf, HERE / "image_types_insert_gif.pdf", tmp_path)


def test_insert_g4_tiff(tmp_path):
    pdf = fpdf.FPDF()
    pdf.add_page()
    pdf.image(HERE / "test.tiff", x=15, y=15)
    assert_pdf_equal(pdf, HERE / "image_types_insert_tiff.pdf", tmp_path)


def test_insert_tiff_cmyk(tmp_path):
    pdf = fpdf.FPDF()
    pdf.add_page()
    pdf.image(HERE / "insert_images_insert_tiff_cmyk.tiff", x=15, y=15)
    assert_pdf_equal(pdf, HERE / "image_types_insert_tiff_cmyk.pdf", tmp_path)


def test_insert_pillow(tmp_path):
    pdf = fpdf.FPDF()
    pdf.add_page()
    img = Image.open(HERE / "insert_images_insert_png.png")
    pdf.image(img, x=15, y=15, h=140)
    assert_pdf_equal(pdf, HERE / "image_types_insert_png.pdf", tmp_path)


def test_insert_pillow_issue_139(tmp_path):
    pdf = fpdf.FPDF()
    pdf.add_page()
    font = ImageFont.truetype(f"{HERE}/../../fonts/DejaVuSans.ttf", 40)
    for y in range(5):
        for x in range(4):
            img = Image.new(mode="RGB", size=(100, 100), color=(60, 255, 10))
            ImageDraw.Draw(img).text((20, 20), f"{y}{x}", fill="black", font=font)
            pdf.image(img, x=x * 50 + 5, y=y * 50 + 5, w=45)
    assert_pdf_equal(pdf, HERE / "insert_pillow_issue_139.pdf", tmp_path)


def test_insert_bytesio(tmp_path):
    pdf = fpdf.FPDF()
    pdf.add_page()
    img = Image.open(HERE / "insert_images_insert_png.png")
    img_bytes = io.BytesIO()
    img.save(img_bytes, "PNG")
    pdf.image(img_bytes, x=15, y=15, h=140)
    assert_pdf_equal(pdf, HERE / "image_types_insert_png.pdf", tmp_path)
    assert not img_bytes.closed  # cf. issue #881


def test_insert_bytes(tmp_path):
    pdf = fpdf.FPDF()
    pdf.add_page()
    img = Image.open(HERE / "insert_images_insert_png.png")
    img_bytes = io.BytesIO()
    img.save(img_bytes, "PNG")
    pdf.image(img_bytes.getvalue(), x=15, y=15, h=140)
    assert_pdf_equal(pdf, HERE / "image_types_insert_png.pdf", tmp_path)
