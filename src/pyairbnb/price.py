import json
from curl_cffi import requests
import pyairbnb.utils as utils
from urllib.parse import urlencode

ep = "https://www.airbnb.com/api/v3/StaysPdpSections/80c7889b4b0027d99ffea830f6c0d4911a6e863a957cbe1044823f0fc746bf1f"

def get(api_key: str, cookies: list, impression_id: str, product_id: str, checkIn: str, checkOut: str, adults: int, currency: str, language: str, proxy_url: str = None) -> (str):
    headers = {
        "Accept": "application/json",
        "Content-Type": "application/json",
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "X-Airbnb-Api-Key": api_key,
    }

    extension = {
        "persistedQuery": {
            "version": 1,
            "sha256Hash": "80c7889b4b0027d99ffea830f6c0d4911a6e863a957cbe1044823f0fc746bf1f",
        },
    }

    variablesData = {
        "id": product_id,
        "pdpSectionsRequest": {
            "adults": str(adults),
            "bypassTargetings": False,
            "categoryTag": None,
            "causeId": None,
            "children": None,
            "disasterId": None,
            "discountedGuestFeeVersion": None,
            "displayExtensions": None,
            "federatedSearchId": None,
            "forceBoostPriorityMessageType": None,
            "infants": None,
            "interactionType": None,
            "layouts": ["SIDEBAR", "SINGLE_COLUMN"],
            "pets": 0,
            "pdpTypeOverride": None,
            "photoId": None,
            "preview": False,
            "previousStateCheckIn": None,
            "previousStateCheckOut": None,
            "priceDropSource": None,
            "privateBooking": False,
            "promotionUuid": None,
            "relaxedAmenityIds": None,
            "searchId": None,
            "selectedCancellationPolicyId": None,
            "selectedRatePlanId": None,
            "splitStays": None,
            "staysBookingMigrationEnabled": False,
            "translateUgc": None,
            "useNewSectionWrapperApi": False,
            "sectionIds": [
                "BOOK_IT_FLOATING_FOOTER",
                "POLICIES_DEFAULT",
                "EDUCATION_FOOTER_BANNER_MODAL",
                "BOOK_IT_SIDEBAR",
                "URGENCY_COMMITMENT_SIDEBAR",
                "BOOK_IT_NAV",
                "MESSAGE_BANNER",
                "HIGHLIGHTS_DEFAULT",
                "EDUCATION_FOOTER_BANNER",
                "URGENCY_COMMITMENT",
                "BOOK_IT_CALENDAR_SHEET",
                "CANCELLATION_POLICY_PICKER_MODAL"
            ],
            "checkIn": checkIn,
            "checkOut": checkOut,
            "p3ImpressionId": impression_id,
        },
    }

    query = {
        "operationName": "StaysPdpSections",
        "locale": language,
        "currency": currency,
        "variables": json.dumps(variablesData),
        "extensions": json.dumps(extension),
    }

    url = f"{ep}?{urlencode(query)}"

    session = requests.Session()
    if proxy_url:
        session.proxies = {"http": proxy_url, "https": proxy_url}

    session.cookies.update(cookies)
    response = session.get(url, headers=headers)
    response.raise_for_status()

    data = response.json()

    sections = utils.get_nested_value(data, "data.presentation.stayProductDetailPage.sections.sections", {})
    priceGroups = utils.get_nested_value(data, "data.presentation.stayProductDetailPage.sections.metadata.bookingPrefetchData.barPrice.explanationData.priceGroups", [])

    finalData = {
        "raw": priceGroups
    }

    for section in sections:
        if section['sectionId'] == "BOOK_IT_SIDEBAR":
            price_data = utils.get_nested_value(section, "section.structuredDisplayPrice", {})
            finalData["main"] = {
                "price": utils.get_nested_value(price_data, "primaryLine.price", {}),
                "discountedPrice": utils.get_nested_value(price_data, "primaryLine.discountedPrice", {}),
                "originalPrice": utils.get_nested_value(price_data, "primaryLine.originalPrice", {}),
                "qualifier": utils.get_nested_value(price_data, "primaryLine.qualifier", {}),
            }

            finalData["details"] = {}
            details = utils.get_nested_value(price_data, "explanationData.priceDetails", {})
            for detail in details:
                for item in utils.get_nested_value(detail, "items", {}):
                    finalData["details"][item["description"]] = item["priceString"]

            return finalData

    return finalData
