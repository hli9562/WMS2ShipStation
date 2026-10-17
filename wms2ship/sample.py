"""Generate synthetic exports only. stdout is XLSX bytes, never real customer data."""

import argparse
import io
import sys

from openpyxl import Workbook


def sample_workbook(country="US", count=1, prefix="DEMO"):
    book = Workbook()
    sheet = book.active
    sheet.title = "出库单"
    sheet.append(
        [
            "Outbound Order No/出库单号",
            "Platform Number/平台单号",
            "SKU varieties/SKU品种数",
            "Total Qty of SKU/总数量",
            "Package Qty/包裹数量",
            "Recipient/收件人",
            "Telephone/电话",
            "Email/邮箱",
            "Company/公司名称",
            "Country/Region/国家/地区",
            "Province Name/省州名称",
            "Province Code/省州编码",
            "City/城市名称",
            "区县/District",
            "Post code/邮编",
            "House No./门牌号",
            "Address1/地址1",
            "Address2/地址2",
            r"Package 1\nTracking No./物流跟踪号",
            r"Package 1\nPackage Size/包裹尺寸",
            r"Package 1\nPackage Size/包裹长",
            r"Package 1\nPackage Size/包裹宽",
            r"Package 1\nPackage Size/包裹高",
            r"Package 1\nPackage Weight/包裹重量",
            r"SKU 1\nSKU",
            r"SKU 1\nBarcode/产品条码",
            r"SKU 1\nProduct Name/产品名称",
        ]
    )
    pick = book.create_sheet("拣货库位明细")
    pick.append(
        [
            "Outbound Order No/出库单号",
            "Client/客户",
            "Platform Number/平台单号",
            "Reference order No./参考单号",
            "Wave No./关联波次号",
            r"SKU 1\nSKU",
            r"SKU 1\nProduct Name/产品名称",
            r"SKU 1\nOutbound Qty/出库数量",
            r"SKU 1\nRecommended Picking Location/推荐拣货库位1",
            r"SKU 1\nRecommended Picking Quantity/推荐拣货数量1",
            r"Package 1\nTracking No./物流跟踪号",
        ]
    )
    for index in range(count):
        order = f"{prefix}-{index + 1:03d}"
        sheet.append(
            [
                order,
                f"PLATFORM-{order}",
                1,
                2,
                1,
                "Synthetic Recipient",
                "+15555550100",
                "",
                "",
                country,
                "",
                "AB" if country == "CA" else "TX",
                "Synthetic City",
                "",
                "T0A 0A0" if country == "CA" else "77494",
                "",
                "100 Synthetic Street",
                "",
                "",
                "20.000*18.500*14.000*cm",
                "20.000",
                "18.500",
                "14.000",
                "0.460kg",
                "TEST-SKU",
                "TEST-BARCODE",
                "Synthetic test item",
            ]
        )
        pick.append(
            [
                order,
                "Synthetic Client",
                f"PLATFORM-{order}",
                "",
                "",
                "TEST-SKU",
                "Synthetic test item",
                2,
                "TEST-LOCATION",
                2,
                "",
            ]
        )
    output = io.BytesIO()
    book.save(output)
    return output.getvalue()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--country", choices=["US", "CA"], default="US")
    args = parser.parse_args()
    sys.stdout.buffer.write(sample_workbook(args.country))
