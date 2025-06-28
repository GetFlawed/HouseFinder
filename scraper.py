import os
import json
import re
from typing import List, Dict, Optional, Set
from dataclasses import dataclass
import requests
from bs4 import BeautifulSoup
import logging

# --- Configuration ---
logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s"
)

# Using a session with more comprehensive headers to appear like a real browser
session = requests.Session()
session.headers.update(
    {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,image/apng,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
        "Accept-Encoding": "gzip, deflate, br",
        "Connection": "keep-alive",
        "Upgrade-Insecure-Requests": "1",
        "Cache-Control": "max-age=0",
    }
)

# File to store URLs of listings that have already been sent
SENT_LISTINGS_FILE = "sent_listings.json"


# --- Data Structure ---
@dataclass
class Property:
    """A dataclass to hold property information."""

    name: str
    link: str
    image: str
    price: str
    bedrooms: int
    bathrooms: int
    source: str


# --- Scraping Functions ---

def scrape_rightmove(url: str) -> List[Property]:
    """
    Scrapes property listings from a Rightmove URL.
    UPDATED: Now parses the __NEXT_DATA__ JSON object.
    """
    logging.info("Scraping Rightmove...")
    properties = []
    try:
        response = session.get(url)
        response.raise_for_status()
        soup = BeautifulSoup(response.text, "html.parser")

        # UPDATED: Rightmove now uses a __NEXT_DATA__ script tag like Zoopla.
        script = soup.find("script", {"id": "__NEXT_DATA__"})
        if not script:
            logging.warning("Could not find __NEXT_DATA__ script on Rightmove.")
            return []

        data = json.loads(script.string)
        # The path to the properties list has changed accordingly.
        listings = data.get("props", {}).get("pageProps", {}).get("properties", [])

        for listing in listings:
            try:
                prop = Property(
                    name=listing.get("displayAddress", "N/A"),
                    link=f"https://www.rightmove.co.uk{listing.get('propertyUrl', '')}",
                    image=listing.get("propertyImages", {}).get(
                        "mainImageSrc", ""
                    ),
                    price=listing.get("price", {}).get("displayPrices", [{}])[
                        0
                    ].get("displayPrice", "N/A"),
                    bedrooms=listing.get("bedrooms", 0),
                    bathrooms=listing.get("bathrooms", 0),
                    source="Rightmove",
                )
                properties.append(prop)
            except (KeyError, IndexError) as e:
                logging.warning(
                    f"Skipping a Rightmove listing due to parsing error: {e}"
                )
                continue

    except requests.RequestException as e:
        logging.error(f"Error scraping Rightmove: {e}")
    return properties


def scrape_zoopla(url: str) -> List[Property]:
    """
    Scrapes property listings from a Zoopla URL.
    NOTE: The request headers in the session object are critical for this to work.
    """
    logging.info("Scraping Zoopla...")
    properties = []
    try:
        response = session.get(url)
        response.raise_for_status()
        soup = BeautifulSoup(response.text, "html.parser")

        script = soup.find("script", {"id": "__NEXT_DATA__"})
        if not script:
            logging.warning("Could not find __NEXT_DATA__ script on Zoopla.")
            return []

        data = json.loads(script.string)
        listings = (
            data.get("props", {})
            .get("pageProps", {})
            .get("regularListings", {})
            .get("listings", [])
        )

        for listing in listings:
            try:
                prop = Property(
                    name=listing.get("title", "N/A"),
                    link=f"https://www.zoopla.co.uk{listing.get('listingUris', {}).get('detail', '')}",
                    image=listing.get("image", {}).get("url", ""),
                    price=listing.get("pricing", {}).get("label", "N/A"),
                    bedrooms=listing.get("beds", 0),
                    bathrooms=listing.get("baths", 0),
                    source="Zoopla",
                )
                properties.append(prop)
            except (KeyError, IndexError) as e:
                logging.warning(f"Skipping a Zoopla listing due to parsing error: {e}")
                continue

    except requests.RequestException as e:
        logging.error(f"Error scraping Zoopla: {e}")
    return properties


def scrape_onthemarket(url: str) -> List[Property]:
    """
    Scrapes property listings from an OnTheMarket URL.
    This is less robust as it relies on specific CSS classes.
    """
    logging.info("Scraping OnTheMarket...")
    properties = []
    try:
        response = session.get(url)
        response.raise_for_status()
        soup = BeautifulSoup(response.text, "html.parser")

        # Improved check: See if the main container exists.
        property_list_container = soup.select_one("#properties-list-tab-panel")
        if not property_list_container:
            logging.warning(
                "OnTheMarket page structure may have changed; main property container not found."
            )
            return []

        # Selectors for OnTheMarket. These have been verified as still correct.
        for card in property_list_container.select("li.otm-PropertyCard"):
            try:
                name_tag = card.select_one("span.otm-PropertyCard-address")
                price_tag = card.select_one("div.otm-PropertyCard-price")
                link_tag = card.select_one("a.otm-PropertyCard-link")
                img_tag = card.select_one("img.otm-PropertyCard-image")

                features = card.select("div.otm-PropertyCard-features span")
                beds = 0
                baths = 0
                for feature in features:
                    text = feature.get_text(strip=True).lower()
                    if "bed" in text:
                        beds = int(re.search(r"\d+", text).group())
                    if "bath" in text:
                        baths = int(re.search(r"\d+", text).group())

                if name_tag and price_tag and link_tag:
                    prop = Property(
                        name=name_tag.get_text(strip=True),
                        link=f"https://www.onthemarket.com{link_tag['href']}",
                        image=img_tag["src"] if img_tag else "",
                        price=price_tag.get_text(strip=True),
                        bedrooms=beds,
                        bathrooms=baths,
                        source="OnTheMarket",
                    )
                    properties.append(prop)
            except (AttributeError, KeyError, TypeError, ValueError) as e:
                logging.warning(
                    f"Skipping an OnTheMarket listing due to parsing error: {e}"
                )
                continue

    except requests.RequestException as e:
        logging.error(f"Error scraping OnTheMarket: {e}")
    return properties


# --- State Management ---


def load_sent_listings() -> Set[str]:
    """Loads the set of sent listing URLs from the file."""
    try:
        with open(SENT_LISTINGS_FILE, "r") as f:
            # Handle case where the file is empty
            content = f.read()
            if not content:
                return set()
            return set(json.loads(content))
    except (FileNotFoundError, json.JSONDecodeError):
        return set()


def save_sent_listings(urls: Set[str]):
    """Saves the current set of listing URLs to the file."""
    with open(SENT_LISTINGS_FILE, "w") as f:
        json.dump(list(urls), f, indent=2)


# --- Notification ---


def send_discord_notification(prop: Property, webhook_url: str):
    """Sends a single property listing to a Discord webhook."""
    embed = {
        "title": prop.name,
        "url": prop.link,
        "color": {
            "Rightmove": 3447003,
            "Zoopla": 8359053,
            "OnTheMarket": 15158332,
        }.get(prop.source, 0),
        "fields": [
            {"name": "Price", "value": prop.price, "inline": True},
            {"name": "Bedrooms", "value": str(prop.bedrooms), "inline": True},
            {"name": "Bathrooms", "value": str(prop.bathrooms), "inline": True},
        ],
        "image": {"url": prop.image},
        "footer": {"text": f"Source: {prop.source}"},
    }

    payload = {"embeds": [embed]}
    try:
        response = requests.post(webhook_url, json=payload)
        response.raise_for_status()
        logging.info(f"Successfully sent notification for: {prop.name}")
    except requests.RequestException as e:
        logging.error(f"Failed to send Discord notification: {e}")


# --- Main Execution ---


def main():
    """Main function to run the scraper."""
    webhook_url = os.getenv("DISCORD_WEBHOOK_URL")
    if not webhook_url:
        logging.error("DISCORD_WEBHOOK_URL environment variable not set.")
        return

    urls = {
        "rightmove": "https://www.rightmove.co.uk/property-to-rent/find.html?searchLocation=Guildford+Station&useLocationIdentifier=true&locationIdentifier=STATION%5E4037&radius=0.0&minPrice=100&maxPrice=1500&minBedrooms=1&maxBedrooms=2&_includeLetAgreed=on&maxBathrooms=2&index=0&sortType=6&channel=RENT&transactionType=LETTING&displayLocationIdentifier=undefined&minBathrooms=1&letType=longTerm&mustHave=parking&dontShow=houseShare%2Cretirement%2Cstudent&maxDaysSinceAdded=1",
        "zoopla": "https://www.zoopla.co.uk/to-rent/property/schools/secondary/guildford-centre/?added=24_hours&baths_max=2&baths_min=1&beds_max=2&beds_min=1&feature=has_parking_garage&is_retirement_home=false&is_shared_accommodation=false&is_student_accommodation=false&price_frequency=per_month&price_max=1500&q=Guildford%20Centre%2C%20Surrey%2C%20GU1&radius=1&search_source=to-rent",
        "onthemarket": "https://www.onthemarket.com/to-rent/property/central-guildford/?let-length=long-term&max-bedrooms=2&min-bedrooms=1&max-price=1500&radius=1.0&recently-added=24-hours&shared=false&student=false",
    }

    all_listings = []
    all_listings.extend(scrape_rightmove(urls["rightmove"]))
    all_listings.extend(scrape_zoopla(urls["zoopla"]))
    all_listings.extend(scrape_onthemarket(urls["onthemarket"]))

    if not all_listings:
        logging.info("No new listings found across all sites in this run.")
        # We still need to save state in case the previous run had listings
        # that have now expired.
        save_sent_listings(set())
        return

    sent_urls = load_sent_listings()
    current_urls = {p.link for p in all_listings}
    new_listings = [p for p in all_listings if p.link not in sent_urls]

    logging.info(f"Found {len(all_listings)} total listings.")
    logging.info(f"Found {len(new_listings)} new listings to notify.")

    for prop in new_listings:
        send_discord_notification(prop, webhook_url)

    save_sent_listings(current_urls)
    logging.info("Finished run.")


if __name__ == "__main__":
    main()
