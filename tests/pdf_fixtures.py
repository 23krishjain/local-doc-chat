"""Synthetic PDFs built with the same parser dependency; no private documents."""
from pypdf import PdfWriter
from pypdf.generic import DictionaryObject, NameObject, DecodedStreamObject


def make_pdf(path, texts, password=None):
    writer = PdfWriter()
    for text in texts:
        page = writer.add_blank_page(width=400, height=400)
        if text is not None:
            font = DictionaryObject({NameObject('/Type'): NameObject('/Font'),
                                     NameObject('/Subtype'): NameObject('/Type1'),
                                     NameObject('/BaseFont'): NameObject('/Helvetica')})
            page[NameObject('/Resources')] = DictionaryObject({NameObject('/Font'): DictionaryObject({NameObject('/F1'): font})})
            # Fixture strings are ASCII; escape PDF literal-string syntax.
            escaped = text.replace('\\', '\\\\').replace('(', '\\(').replace(')', '\\)')
            stream = DecodedStreamObject()
            stream.set_data(f'BT /F1 14 Tf 25 350 Td ({escaped}) Tj ET'.encode('ascii'))
            page[NameObject('/Contents')] = writer._add_object(stream)
    if password:
        writer.encrypt(password)
    writer.write(path)
