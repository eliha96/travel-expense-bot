import openpyxl
from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
from openpyxl.utils import get_column_letter
from datetime import datetime
from pathlib import Path
from typing import Dict, Any, List
from config import REPORTS_DIR, RATE_PER_KM
from database import get_month_trips

def generate_monthly_report(year: int, month: int) -> Path:
    """
    Generates an Excel workbook formatted exactly according to the template.
    Returns the path to the generated .xlsx file.
    """
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = f"החזרי נסיעות {month:02d}-{year}"
    ws.sheet_view.rightToLeft = True  # RTL for Hebrew

    # Styles
    font_title = Font(name="Calibri", size=13, bold=True, color="1F497D")
    font_header = Font(name="Calibri", size=11, bold=True, color="000000")
    font_bold = Font(name="Calibri", size=11, bold=True)
    font_regular = Font(name="Calibri", size=11)
    
    fill_car_header = PatternFill(start_color="DCE6F1", end_color="DCE6F1", fill_type="solid")
    fill_transit_header = PatternFill(start_color="E4DFEC", end_color="E4DFEC", fill_type="solid")
    fill_total_header = PatternFill(start_color="FDE9D9", end_color="FDE9D9", fill_type="solid")
    fill_total_row = PatternFill(start_color="F2F2F2", end_color="F2F2F2", fill_type="solid")
    
    thin_border_side = Side(border_style="thin", color="B0B0B0")
    double_border_bottom = Side(border_style="double", color="000000")
    
    cell_border = Border(left=thin_border_side, right=thin_border_side, top=thin_border_side, bottom=thin_border_side)
    total_border = Border(left=thin_border_side, right=thin_border_side, top=thin_border_side, bottom=double_border_bottom)

    align_center = Alignment(horizontal="center", vertical="center")
    align_right = Alignment(horizontal="right", vertical="center")

    # Row 1: Section Titles
    # Car Title: A1:E1
    ws.merge_cells("A1:E1")
    ws["A1"] = "החזרי נסיעות לפי קילומטרים"
    ws["A1"].font = font_title
    ws["A1"].alignment = align_center
    ws["A1"].fill = fill_car_header

    # Transit Title: G1:I1
    ws.merge_cells("G1:I1")
    ws["G1"] = "החזרי נסיעות בתחבורה ציבורית"
    ws["G1"].font = font_title
    ws["G1"].alignment = align_center
    ws["G1"].fill = fill_transit_header

    # Grand Total Title: K1:K2 merged or K2
    ws["K1"] = "סיכום חודשי"
    ws["K1"].font = font_title
    ws["K1"].alignment = align_center
    ws["K1"].fill = fill_total_header

    # Row 2: Column Headers
    car_headers = ["תאריך", "פירוט", "ק\"מ", "החזר לק\"מ", "עלות נסיעה"]
    for col_idx, header in enumerate(car_headers, start=1):
        cell = ws.cell(row=2, column=col_idx, value=header)
        cell.font = font_header
        cell.alignment = align_center
        cell.fill = fill_car_header
        cell.border = cell_border

    transit_headers = ["תאריך", "פירוט", "עלות נסיעה"]
    for col_idx, header in enumerate(transit_headers, start=7):
        cell = ws.cell(row=2, column=col_idx, value=header)
        cell.font = font_header
        cell.alignment = align_center
        cell.fill = fill_transit_header
        cell.border = cell_border

    # Grand Total Header in K2
    cell_k2 = ws["K2"]
    cell_k2.value = "סה\"כ החזרי נסיעות חודשיים"
    cell_k2.font = font_header
    cell_k2.alignment = align_center
    cell_k2.fill = fill_total_header
    cell_k2.border = cell_border

    # Fetch data
    data = get_month_trips(year, month)
    car_trips = data["car_trips"]
    transit_trips = data["transit_trips"]

    # Minimum rows for visual template (at least 20 rows or trip count)
    num_rows = max(len(car_trips), len(transit_trips), 22)
    start_row = 3

    for i in range(num_rows):
        current_row = start_row + i

        # Car section (Cols A-E)
        if i < len(car_trips):
            trip = car_trips[i]
            c_date = trip["date"]
            c_desc = trip["destination"]
            c_km = trip["distance_km"]
            c_rate = trip["rate_per_km"]
        else:
            c_date = ""
            c_desc = ""
            c_km = ""
            c_rate = RATE_PER_KM

        ws.cell(row=current_row, column=1, value=c_date).alignment = align_center
        ws.cell(row=current_row, column=2, value=c_desc).alignment = align_right
        
        km_cell = ws.cell(row=current_row, column=3, value=c_km)
        km_cell.alignment = align_center
        km_cell.number_format = "0.0"
        
        rate_cell = ws.cell(row=current_row, column=4, value=c_rate)
        rate_cell.alignment = align_center
        rate_cell.number_format = "0.00"

        cost_cell = ws.cell(row=current_row, column=5)
        cost_cell.value = f"=IF(C{current_row}<>\"\", C{current_row}*D{current_row}, 0)"
        cost_cell.alignment = align_center
        cost_cell.number_format = "0.00"

        for col in range(1, 6):
            cell = ws.cell(row=current_row, column=col)
            cell.font = font_regular
            cell.border = cell_border

        # Transit section (Cols G-I)
        if i < len(transit_trips):
            t_trip = transit_trips[i]
            t_date = t_trip["date"]
            t_desc = t_trip["details"]
            t_cost = t_trip["cost"]
        else:
            t_date = ""
            t_desc = ""
            t_cost = ""

        ws.cell(row=current_row, column=7, value=t_date).alignment = align_center
        ws.cell(row=current_row, column=8, value=t_desc).alignment = align_right
        
        t_cost_cell = ws.cell(row=current_row, column=9, value=t_cost if t_cost != "" else "")
        t_cost_cell.alignment = align_center
        if t_cost != "":
            t_cost_cell.number_format = "0.00"

        for col in range(7, 10):
            cell = ws.cell(row=current_row, column=col)
            cell.font = font_regular
            cell.border = cell_border

    total_row = start_row + num_rows

    # Car Totals
    ws.cell(row=total_row, column=1, value="סה\"כ").alignment = align_center
    ws.cell(row=total_row, column=1).font = font_bold
    ws.cell(row=total_row, column=1).fill = fill_total_row
    ws.cell(row=total_row, column=1).border = total_border

    ws.cell(row=total_row, column=2, value="").border = total_border
    ws.cell(row=total_row, column=2).fill = fill_total_row

    total_km_cell = ws.cell(row=total_row, column=3, value=f"=SUM(C3:C{total_row-1})")
    total_km_cell.font = font_bold
    total_km_cell.alignment = align_center
    total_km_cell.fill = fill_total_row
    total_km_cell.number_format = "0.0"
    total_km_cell.border = total_border

    ws.cell(row=total_row, column=4, value="").border = total_border
    ws.cell(row=total_row, column=4).fill = fill_total_row

    total_car_cost_cell = ws.cell(row=total_row, column=5, value=f"=SUM(E3:E{total_row-1})")
    total_car_cost_cell.font = font_bold
    total_car_cost_cell.alignment = align_center
    total_car_cost_cell.fill = fill_total_row
    total_car_cost_cell.number_format = "0.00 ₪"
    total_car_cost_cell.border = total_border

    # Transit Totals
    ws.cell(row=total_row, column=7, value="סה\"כ").alignment = align_center
    ws.cell(row=total_row, column=7).font = font_bold
    ws.cell(row=total_row, column=7).fill = fill_total_row
    ws.cell(row=total_row, column=7).border = total_border

    ws.cell(row=total_row, column=8, value="").border = total_border
    ws.cell(row=total_row, column=8).fill = fill_total_row

    total_transit_cost_cell = ws.cell(row=total_row, column=9, value=f"=SUM(I3:I{total_row-1})")
    total_transit_cost_cell.font = font_bold
    total_transit_cost_cell.alignment = align_center
    total_transit_cost_cell.fill = fill_total_row
    total_transit_cost_cell.number_format = "0.00 ₪"
    total_transit_cost_cell.border = total_border

    # Grand Total (Col K, Row 3)
    grand_total_cell = ws["K3"]
    grand_total_cell.value = f"=E{total_row}+I{total_row}"
    grand_total_cell.font = Font(name="Calibri", size=14, bold=True, color="9C0006")
    grand_total_cell.alignment = align_center
    grand_total_cell.fill = fill_total_header
    grand_total_cell.number_format = "0.00 ₪"
    grand_total_cell.border = total_border

    # Adjust Column Widths
    column_widths = {
        "A": 14, "B": 28, "C": 10, "D": 12, "E": 14,
        "F": 4,
        "G": 14, "H": 28, "I": 14,
        "J": 4,
        "K": 26
    }
    for col_letter, width in column_widths.items():
        ws.column_dimensions[col_letter].width = width

    # Save file
    file_path = REPORTS_DIR / f"travel_report_{year}_{month:02d}.xlsx"
    wb.save(file_path)
    return file_path
