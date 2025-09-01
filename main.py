import requests
from bs4 import BeautifulSoup
import re
import csv
import time

# =============================================================================
# CORE UTILITIES
# =============================================================================
def save_to_csv(data, filename):
    """Save data to CSV file"""
    if not data:
        print("No data to save")
        return
    
    with open(filename, 'w', newline='', encoding='utf-8') as f:
        writer = csv.DictWriter(f, fieldnames=data[0].keys())
        writer.writeheader()
        writer.writerows(data)
    print(f"Data saved to {filename}")

def get_page(url):
    """Fetch webpage and return BeautifulSoup object"""
    try:
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
        }
        response = requests.get(url, headers=headers)
        response.raise_for_status()
        return BeautifulSoup(response.content, 'html.parser')
    except requests.RequestException as e:
        print(f"Error fetching {url}: {e}")
        return None

# =============================================================================
# PAGE-SPECIFIC CRAWLERS
# =============================================================================
def crawl_book_details_from_url(book_url):
    """Extract detailed book information from a specific book URL"""
    soup = get_page(book_url)
    if not soup:
        return {}
    
    book_details = {'source_url': book_url}
    
    # Title
    title_elem = soup.find('span', itemprop='name')
    if not title_elem:
        title_elem = soup.find('h1')
    book_details['title'] = title_elem.get_text().strip() if title_elem else ""
    
    # Authors
    # Find author links only within ancestor with class 'work-title-and-author desktop'
    author_links = []
    ancestor = soup.find('div', class_='work-title-and-author desktop')
    if ancestor:
        author_links = ancestor.find_all('a', itemprop='author')
    book_details['authors'] = [link.get_text().strip() for link in author_links]

    # First published date from <span class="first-published-date" title="First published in YYYY">
    first_pub_span = soup.find('span', class_='first-published-date')
    if first_pub_span and first_pub_span.get_text():
        # Extract year from text like "(1924)"
        year_match = re.search(r'\((\d{4})\)', first_pub_span.get_text())
        if year_match:
            book_details['first_published'] = year_match.group(1)
        else:
            book_details['first_published'] = first_pub_span.get_text().strip()
    else:
        book_details['first_published'] = ""
    
    # Publish date from <span itemprop="datePublished">
    publish_span = soup.find('span', itemprop='datePublished')
    if publish_span:
        book_details['publish_date'] = publish_span.get_text().strip()
    else:
        book_details['publish_date'] = ""
    
    # Subjects/Tags
    subject_links = soup.find_all('a', href=re.compile(r'/subjects/'))
    book_details['subjects'] = [link.get_text().strip() for link in subject_links]
    
    # Languages
    language = soup.find('span', {'itemprop': 'inLanguage'})
    if language:
        book_details['language'] = language.get_text().strip()
    else:
        book_details['language'] = ""
    
    # ISBN - look for specific HTML structure first
    book_details['isbn'] = ""
    
    # Look for dd with itemprop="isbn"
    isbn_dd = soup.find('dd', {'itemprop': 'isbn'})
    if isbn_dd:
        book_details['isbn'] = isbn_dd.get_text().strip()
        
    # Edition count - be more specific with regex
    edition_match = re.search(r'(\d+)\s*editions?\b', soup.get_text(), re.I)
    book_details['edition_count'] = int(edition_match.group(1)) if edition_match else 0
    
    # Rating - look for various rating patterns
    book_details['rating'] = 0.0
    book_details['number_of_ratings'] = 0

    # Look for itemprop="ratingValue" span
    rating_span = soup.find('span', {'itemprop': 'ratingValue'})
    if rating_span:
        rating_text = rating_span.get_text().strip()
        # Extract rating and number of ratings from string like "3.8 (8 ratings)"
        rating_match = re.search(r'(\d\.\d+)\s*\((\d+)\s*ratings?\)', rating_text)
        if rating_match:
            book_details['rating'] = float(rating_match.group(1))
            book_details['number_of_ratings'] = int(rating_match.group(2))
    
    # Pages - look for page count patterns
    book_details['pages'] = 0
    # Look for <span class="edition-pages" itemprop="numberOfPages">
    pages_span = soup.find('span', class_='edition-pages', itemprop='numberOfPages')
    if pages_span and pages_span.get_text().strip().isdigit():
        book_details['pages'] = int(pages_span.get_text().strip())
        
    return book_details

def crawl_book_details_from_csv(csv_file, url_column = 'book_url'):
    """Extract book details from URLs in a CSV file"""
    try:
        # Read CSV file using built-in csv module
        book_details = []
        
        with open(csv_file, 'r', encoding='utf-8') as f:
            reader = csv.DictReader(f)
            rows = list(reader)  # Convert to list to get count
            
            if url_column not in reader.fieldnames:
                print(f"Column '{url_column}' not found in CSV. Available columns: {reader.fieldnames}")
                return []
            
            total_urls = len(rows)
            print(f"Processing {total_urls} book URLs from {csv_file}...")
            
            for idx, row in enumerate(rows):
                url = row[url_column]
                print(f"Processing {idx+1}/{total_urls}: {url}")
                
                details = crawl_book_details_from_url(url)
                if details:
                    # Add original CSV data to details
                    details['original_title'] = row.get('title', '')
                    details['work_key'] = row.get('work_key', '')
                    book_details.append(details)
        
        print(f"Successfully extracted details for {len(book_details)} books")
        return book_details
        
    except Exception as e:
        print(f"Error reading CSV file: {e}")
        return []

def crawl_openlibrary_books_by_subject(subject, max_pages = 3):
    """Extract books for a specific subject from OpenLibrary search API with paging"""
    books = []
    
    for page in range(1, max_pages + 1):
        print(f"Fetching page {page} for subject '{subject}'...")
        
        # Build search URL with page parameter subject_key:"science_fiction" edition_count:{5 TO *}
        search_url = f"https://openlibrary.org/search?q=subject_key%3A%22{subject}%22+edition_count%3A%7B5+TO+*%7D&page={page}"
        
        soup = get_page(search_url)
        if not soup:
            print(f"Failed to fetch page {page}")
            continue
        
        page_books = []
        
        # Look for book results - they're typically in divs with class 'searchResultItem'
        book_items = soup.find_all('div', class_='searchResultItem')
        
        # If no searchResultItem, try alternative selectors
        if not book_items:
            book_items = soup.find_all('div', class_='book-item')
        if not book_items:
            book_items = soup.find_all('li', class_='searchResultItem')
        
        # If no books found on this page, we might have reached the end
        if not book_items:
            print(f"No books found on page {page}, stopping pagination")
            break
        
        for item in book_items:
            # Book title and link
            title_link = item.find('h3').find('a') if item.find('h3') else None
            if not title_link:
                title_link = item.find('a', class_='results')
            
            if not title_link:
                continue
                
            title = title_link.get_text().strip()
            
            # Get the full URL with edition key if present
            href = title_link['href']
            book_url = f"https://openlibrary.org{href}"
            
            # Extract work key from URL (before any query parameters)
            work_key = ""
            if '/works/' in href:
                # Extract work key (e.g., OL27448W from /works/OL27448W/The_Lord_of_the_Rings)
                work_part = href.split('/works/')[-1]
                work_key = work_part.split('/')[0].split('?')[0]  # Get just the work key part
            
            page_books.append({
                'title': title,
                'work_key': work_key,
                'book_url': book_url
            })
        
        books.extend(page_books)
        print(f"Found {len(page_books)} books on page {page}")
        
        # Optional: Add a small delay between requests to be respectful        
        time.sleep(0.5)
    
    print(f"Extracted {len(books)} total books for subject '{subject}' from {max_pages} pages")
    return books

if __name__ == "__main__":
    book_search_list = crawl_openlibrary_books_by_subject('science_fiction', max_pages=1)
    save_to_csv(book_search_list, 'books_science_fiction_search_temp.csv')

    book_details = crawl_book_details_from_csv('books_science_fiction_search_temp.csv')
    save_to_csv(book_details, 'books_science_fiction_detailed_temp.csv')