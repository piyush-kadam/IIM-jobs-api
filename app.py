from flask import Flask, request, jsonify
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from webdriver_manager.chrome import ChromeDriverManager
import time
import uuid
import re

app = Flask(__name__)
sessions = {}

def create_driver():
    chrome_options = Options()
    chrome_options.add_argument("--headless=new")
    chrome_options.add_argument("--no-sandbox")
    chrome_options.add_argument("--disable-dev-shm-usage")
    chrome_options.add_argument("--disable-blink-features=AutomationControlled")
    chrome_options.add_experimental_option("excludeSwitches", ["enable-automation"])
    chrome_options.add_experimental_option('useAutomationExtension', False)
    chrome_options.add_argument("--user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36")
    
    service = Service(ChromeDriverManager().install())
    driver = webdriver.Chrome(service=service, options=chrome_options)
    driver.execute_script("Object.defineProperty(navigator, 'webdriver', {get: () => undefined})")
    return driver

@app.route("/api/login", methods=["POST"])
def login():
    data = request.json
    email = data.get("email")
    password = data.get("password")
    
    if not email or not password:
        return jsonify({"error": "Email and password are required"}), 400

    driver = create_driver()
    session_id = str(uuid.uuid4())
    
    try:
        driver.get("https://www.iimjobs.com/login")
        wait = WebDriverWait(driver, 10)
        
        # Wait for and fill email field
        email_field = wait.until(EC.presence_of_element_located((By.NAME, "email")))
        email_field.clear()
        email_field.send_keys(email)
        
        # Fill password field
        password_field = driver.find_element(By.NAME, "password")
        password_field.clear()
        password_field.send_keys(password)
        
        # Click login button
        login_button = wait.until(EC.element_to_be_clickable((By.XPATH, "//button[contains(text(), 'Login')] | //input[@type='submit' and @value='Login']")))
        driver.execute_script("arguments[0].click();", login_button)
        
        # Wait for login to complete
        time.sleep(5)
        
        # Check if login was successful by looking for logout link or dashboard
        if ("dashboard" in driver.current_url.lower() or 
            "logout" in driver.page_source.lower() or
            "profile" in driver.page_source.lower()):
            
            sessions[session_id] = {"driver": driver, "email": email}
            return jsonify({"message": "Login successful", "session_id": session_id}), 200
        else:
            driver.save_screenshot("login_failed.png")
            driver.quit()
            return jsonify({"error": "Login failed. Check credentials."}), 401

    except Exception as e:
        driver.quit()
        return jsonify({"error": f"Login error: {str(e)}"}), 500

@app.route("/api/jobs", methods=["POST"])
def get_jobs():
    data = request.json
    session_id = data.get("session_id")
    max_jobs = data.get("max_jobs", 100)  # Allow client to specify max jobs, default to 100
    scroll_pages = data.get("scroll_pages", 5)  # Number of pages to scroll through
    
    if not session_id or session_id not in sessions:
        return jsonify({"error": "Invalid session. Please login first."}), 403

    session_data = sessions[session_id]
    driver = session_data["driver"]

    try:
        jobs = []
        wait = WebDriverWait(driver, 15)
        
        print(f"Accessing IIMJobs jobfeed... Target: {max_jobs} jobs, Scroll pages: {scroll_pages}")
        
        # Method 1: Direct access to jobfeed with pagination
        try:
            driver.get("https://www.iimjobs.com/jobfeed")
            time.sleep(5)  # Wait for page to load completely
            
            # Wait for job listings to load
            wait.until(EC.presence_of_element_located((By.TAG_NAME, "body")))
            
            jobs = extract_iimjobs_feed_with_pagination(driver, max_jobs, scroll_pages)
            if jobs:
                return jsonify({"jobs": jobs, "count": len(jobs), "method": "direct_jobfeed_paginated"}), 200
                
        except Exception as e:
            print(f"Direct jobfeed access failed: {str(e)}")
        
        # Method 2: Try alternative job listing page with pagination
        try:
            driver.get("https://www.iimjobs.com/jobs")
            time.sleep(5)
            
            jobs = extract_iimjobs_feed_with_pagination(driver, max_jobs, scroll_pages)
            if jobs:
                return jsonify({"jobs": jobs, "count": len(jobs), "method": "jobs_page_paginated"}), 200
                
        except Exception as e:
            print(f"Jobs page access failed: {str(e)}")
        
        # Method 3: Try search page with pagination
        try:
            driver.get("https://www.iimjobs.com/j")  # Common job search URL pattern
            time.sleep(5)
            
            jobs = extract_iimjobs_feed_with_pagination(driver, max_jobs, scroll_pages)
            if jobs:
                return jsonify({"jobs": jobs, "count": len(jobs), "method": "search_page_paginated"}), 200
                
        except Exception as e:
            print(f"Search page access failed: {str(e)}")
        
        # Method 4: Try multiple job categories/searches
        try:
            jobs = scrape_multiple_job_categories(driver, max_jobs)
            if jobs:
                return jsonify({"jobs": jobs, "count": len(jobs), "method": "multiple_categories"}), 200
                
        except Exception as e:
            print(f"Multiple categories method failed: {str(e)}")
        
        # If no jobs found, provide detailed debug info
        driver.save_screenshot("iimjobs_debug.png")
        
        return jsonify({
            "error": "No job listings found",
            "debug_info": {
                "current_url": driver.current_url,
                "page_title": driver.title,
                "screenshot_saved": "iimjobs_debug.png"
            },
            "suggestion": "Try checking if login is required or if the page structure has changed"
        }), 404

    except Exception as e:
        return jsonify({"error": f"Job fetching failed: {str(e)}"}), 500

def extract_iimjobs_feed_with_pagination(driver, max_jobs=100, scroll_pages=5):
    """Extract jobs with pagination/scrolling support"""
    jobs = []
    
    print(f"Extracting jobs with pagination... Target: {max_jobs}, Scroll pages: {scroll_pages}")
    
    for page in range(scroll_pages):
        print(f"Processing page/scroll {page + 1}")
        
        # Wait for content to load
        time.sleep(3)
        
        # Extract jobs from current page
        current_jobs = extract_iimjobs_feed(driver, max_jobs - len(jobs))
        
        if current_jobs:
            # Remove duplicates based on job title and company
            for job in current_jobs:
                is_duplicate = False
                for existing_job in jobs:
                    if (job.get("title") == existing_job.get("title") and 
                        job.get("company") == existing_job.get("company")):
                        is_duplicate = True
                        break
                
                if not is_duplicate:
                    jobs.append(job)
            
            print(f"Found {len(current_jobs)} jobs on page {page + 1}, Total: {len(jobs)}")
        
        # Break if we have enough jobs
        if len(jobs) >= max_jobs:
            break
        
        # Try to scroll down or go to next page
        if not scroll_or_next_page(driver):
            print("No more pages or scrolling failed")
            break
    
    print(f"Total jobs extracted with pagination: {len(jobs)}")
    return jobs[:max_jobs]  # Return only the requested number

def scroll_or_next_page(driver):
    """Try to scroll down or navigate to next page"""
    try:
        # Method 1: Try to find and click "Next" button
        next_selectors = [
            "//button[contains(text(), 'Next')]",
            "//a[contains(text(), 'Next')]",
            "//button[@title='Next']",
            "//a[@title='Next']",
            ".next-page",
            ".pagination-next",
            "[aria-label='Next']"
        ]
        
        for selector in next_selectors:
            try:
                if selector.startswith("//"):
                    next_button = driver.find_element(By.XPATH, selector)
                else:
                    next_button = driver.find_element(By.CSS_SELECTOR, selector)
                
                if next_button.is_enabled() and next_button.is_displayed():
                    driver.execute_script("arguments[0].click();", next_button)
                    time.sleep(3)
                    return True
            except:
                continue
        
        # Method 2: Try infinite scroll
        last_height = driver.execute_script("return document.body.scrollHeight")
        
        # Scroll down to bottom
        driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
        time.sleep(3)
        
        # Check if more content loaded
        new_height = driver.execute_script("return document.body.scrollHeight")
        
        if new_height > last_height:
            return True
        
        # Method 3: Try loading more content with JavaScript
        load_more_selectors = [
            "//button[contains(text(), 'Load more')]",
            "//button[contains(text(), 'Show more')]",
            "//a[contains(text(), 'Load more')]",
            ".load-more",
            ".show-more"
        ]
        
        for selector in load_more_selectors:
            try:
                if selector.startswith("//"):
                    load_button = driver.find_element(By.XPATH, selector)
                else:
                    load_button = driver.find_element(By.CSS_SELECTOR, selector)
                
                if load_button.is_enabled() and load_button.is_displayed():
                    driver.execute_script("arguments[0].click();", load_button)
                    time.sleep(3)
                    return True
            except:
                continue
        
        return False
        
    except Exception as e:
        print(f"Scroll/pagination error: {str(e)}")
        return False

def scrape_multiple_job_categories(driver, max_jobs=100):
    """Scrape jobs from multiple categories/searches"""
    jobs = []
    
    # Common job search terms and categories
    search_terms = [
        "finance", "marketing", "sales", "hr", "operations", 
        "technology", "manager", "analyst", "executive", "consultant"
    ]
    
    # Try different search URLs
    search_urls = [
        "https://www.iimjobs.com/j?kw=finance",
        "https://www.iimjobs.com/j?kw=marketing", 
        "https://www.iimjobs.com/j?kw=sales",
        "https://www.iimjobs.com/j?kw=manager",
        "https://www.iimjobs.com/j?kw=analyst"
    ]
    
    for i, url in enumerate(search_urls):
        if len(jobs) >= max_jobs:
            break
            
        try:
            print(f"Scraping category {i+1}: {url}")
            driver.get(url)
            time.sleep(4)
            
            category_jobs = extract_iimjobs_feed(driver, max_jobs - len(jobs))
            
            if category_jobs:
                # Remove duplicates
                for job in category_jobs:
                    is_duplicate = False
                    for existing_job in jobs:
                        if (job.get("title") == existing_job.get("title") and 
                            job.get("company") == existing_job.get("company")):
                            is_duplicate = True
                            break
                    
                    if not is_duplicate:
                        jobs.append(job)
                
                print(f"Added {len(category_jobs)} jobs from category, Total: {len(jobs)}")
        
        except Exception as e:
            print(f"Error scraping category {url}: {str(e)}")
            continue
    
    return jobs[:max_jobs]

def extract_iimjobs_feed(driver, max_jobs=50):
    """Extract jobs specifically from IIMJobs feed format"""
    jobs = []
    
    print(f"Extracting jobs from IIMJobs feed... Max: {max_jobs}")
    
    # Wait a bit more for dynamic content to load
    time.sleep(3)
    
    # Extended list of job selectors
    job_selectors = [
        # IIMJobs specific selectors
        "[data-job-id]",
        ".job-item",
        ".job-card", 
        ".feed-item",
        ".job-listing",
        ".job-row",
        ".job-tile",
        ".job-container",
        # Generic selectors
        "div[class*='job']",
        "li[class*='job']",
        "div[class*='listing']",
        "div[class*='card']",
        ".card",
        # More specific patterns
        "div:has(img[src*='logo'])",
        "div:has(a[href*='job'])",
        "div:has(a[href*='view'])",
        # Table-based layouts
        "tr[class*='job']",
        "tbody tr"
    ]
    
    job_containers = []
    
    for selector in job_selectors:
        try:
            elements = driver.find_elements(By.CSS_SELECTOR, selector)
            if elements and len(elements) > 1:  # We want multiple job listings
                print(f"Found {len(elements)} potential job containers with selector: {selector}")
                job_containers = elements
                break
        except Exception as e:
            print(f"Selector {selector} failed: {str(e)}")
            continue
    
    # If specific selectors don't work, try a more generic approach
    if not job_containers:
        print("Trying generic approach to find job listings...")
        
        # Look for elements containing job-related keywords
        job_keywords = ["hiring", "experience", "years", "salary", "apply", "job", "position", "role"]
        
        try:
            # Find divs that contain multiple job-related keywords
            all_divs = driver.find_elements(By.TAG_NAME, "div")
            potential_containers = []
            
            for div in all_divs:
                text = div.text.lower()
                keyword_count = sum(1 for keyword in job_keywords if keyword in text)
                
                if keyword_count >= 2 and len(text) > 50:  # At least 2 keywords and substantial text
                    potential_containers.append(div)
            
            if len(potential_containers) > 3:
                job_containers = potential_containers[:max_jobs * 2]  # Take more than needed
                print(f"Found {len(job_containers)} job containers using keyword approach")
        except:
            pass
    
    # Extract job data from containers
    extracted_count = 0
    for i, container in enumerate(job_containers):
        if extracted_count >= max_jobs:
            break
            
        try:
            job_data = extract_iimjobs_job_data(container, driver)
            if job_data:
                jobs.append(job_data)
                extracted_count += 1
                print(f"Extracted job {extracted_count}: {job_data.get('title', 'No title')} at {job_data.get('company', 'No company')}")
        except Exception as e:
            print(f"Error extracting job {i}: {str(e)}")
            continue
    
    print(f"Total jobs extracted: {len(jobs)}")
    return jobs

def extract_iimjobs_job_data(container, driver):
    """Extract job data specifically for IIMJobs format"""
    job_data = {}
    
    try:
        container_text = container.text.strip()
        
        if len(container_text) < 20:
            return None
        
        # company
        company_selectors = [
            "h3", "h4", "h2", ".company", ".company-name", "[data-company]",
            "strong", "b", ".employer", ".org-name"
        ]
        for selector in company_selectors:
            try:
                elem = container.find_element(By.CSS_SELECTOR, selector)
                text = elem.text.strip()
                if text and len(text) > 1 and len(text) < 100:
                    job_data["company"] = text
                    break
            except:
                continue
        
        # title
        title_selectors = [
            "h1", "h2", "h3", "h4", "h5", ".title", ".job-title", ".position",
            "a[href*='job']", "a[href*='view']", ".role", ".designation"
        ]
        for selector in title_selectors:
            try:
                elem = container.find_element(By.CSS_SELECTOR, selector)
                text = elem.text.strip()
                if text and text != job_data.get("company") and len(text) > 3:
                    job_data["title"] = text
                    break
            except:
                continue
        
        # experience
        experience_patterns = [
            r'(\d+\s*-\s*\d+\s*[Yy]rs?)',
            r'(\d+\+?\s*[Yy]rs?)',
            r'(\d+\s*to\s*\d+\s*[Yy]ears?)',
            r'(Fresher)',
            r'(Entry\s*level)'
        ]
        for pattern in experience_patterns:
            match = re.search(pattern, container_text, re.IGNORECASE)
            if match:
                job_data["experience"] = match.group(1)
                break
        
        # location
        location_keywords = [
            "Hyderabad", "Bangalore", "Mumbai", "Delhi", "Chennai", "Pune", "Kolkata", 
            "Gurgaon", "Noida", "Ahmedabad", "Jaipur", "Indore", "Bhopal", "Lucknow",
            "Kochi", "Coimbatore", "Vadodara", "Nagpur", "Visakhapatnam", "Surat",
            "Remote", "Work from home", "WFH"
        ]
        for location in location_keywords:
            if location.lower() in container_text.lower():
                job_data["location"] = location
                break
        
        # salary
        salary_patterns = [
            r'(₹\s*\d+[,\d]*\s*-\s*₹?\s*\d+[,\d]*)',
            r'(\d+\s*-\s*\d+\s*LPA)',
            r'(\d+\s*-\s*\d+\s*Lakh)',
            r'(Not\s*disclosed)',
            r'(Salary\s*negotiable)'
        ]
        for pattern in salary_patterns:
            match = re.search(pattern, container_text, re.IGNORECASE)
            if match:
                job_data["salary"] = match.group(1)
                break
        
        # link
        try:
            link_elem = container.find_element(By.TAG_NAME, "a")
            href = link_elem.get_attribute("href")
            if href:
                if href.startswith("http"):
                    job_data["link"] = href
                elif href.startswith("/"):
                    job_data["link"] = f"https://www.iimjobs.com{href}"
        except:
            pass
        
        # posted date
        date_patterns = [
            r'(posted\s+today)',
            r'(posted\s+yesterday)',
            r'(posted\s+\d+\s+days?\s+ago)',
            r'(\d+\s+days?\s+ago)',
            r'(few\s+hours?\s+ago)'
        ]
        for pattern in date_patterns:
            match = re.search(pattern, container_text.lower())
            if match:
                job_data["posted"] = match.group(1).title()
                break
        
        # job type
        job_type_keywords = ["Full-time", "Part-time", "Contract", "Permanent", "Temporary", "Internship"]
        for job_type in job_type_keywords:
            if job_type.lower() in container_text.lower():
                job_data["job_type"] = job_type
                break
        
        # fallback from raw lines
        if not job_data.get("title") and not job_data.get("company"):
            lines = [line.strip() for line in container_text.split('\n') if line.strip()]
            if lines:
                for i, line in enumerate(lines[:5]):
                    if len(line) > 5 and len(line) < 80:
                        if not job_data.get("title"):
                            job_data["title"] = line
                        elif not job_data.get("company") and line != job_data["title"]:
                            job_data["company"] = line
                            break

        # LOGO
        try:
            img_elem = container.find_element(By.CSS_SELECTOR, "img")
            logo_url = img_elem.get_attribute("src")
            if logo_url and logo_url.startswith("http"):
                job_data["logo"] = logo_url
        except:
            job_data["logo"] = ""
        
        # metadata
        job_data["raw_text"] = container_text[:500] if container_text else ""
        job_data["extraction_method"] = "enhanced_iimjobs"
        
        return job_data if (job_data.get("title") or job_data.get("company")) else None
        
    except Exception as e:
        print(f"Error in extract_iimjobs_job_data: {str(e)}")
        return None

@app.route("/api/logout", methods=["POST"])
def logout():
    data = request.json
    session_id = data.get("session_id")
    
    if session_id in sessions:
        try:
            sessions[session_id]["driver"].quit()
        except:
            pass
        del sessions[session_id]
        return jsonify({"message": "Logged out successfully"}), 200
    
    return jsonify({"error": "Session not found"}), 404

@app.route("/api/debug", methods=["POST"])
def debug_page():
    """Debug endpoint to see current page content"""
    data = request.json
    session_id = data.get("session_id")
    
    if not session_id or session_id not in sessions:
        return jsonify({"error": "Invalid session"}), 403
    
    driver = sessions[session_id]["driver"]
    
    try:
        driver.save_screenshot("debug_page.png")
        
        # Get navigation links
        nav_links = []
        try:
            links = driver.find_elements(By.TAG_NAME, "a")[:30]  # Increased from 20
            nav_links = [{"text": link.text.strip(), "href": link.get_attribute("href")} 
                        for link in links if link.get_attribute("href")]
        except:
            pass
        
        # Get form elements
        forms = []
        try:
            form_elements = driver.find_elements(By.TAG_NAME, "form")
            for form in form_elements:
                inputs = form.find_elements(By.TAG_NAME, "input")
                form_data = {
                    "action": form.get_attribute("action"),
                    "method": form.get_attribute("method"),
                    "inputs": [{"name": inp.get_attribute("name"), 
                              "type": inp.get_attribute("type")} for inp in inputs]
                }
                forms.append(form_data)
        except:
            pass
        
        return jsonify({
            "current_url": driver.current_url,
            "page_title": driver.title,
            "page_source_length": len(driver.page_source),
            "screenshot_saved": "debug_page.png",
            "navigation_links": nav_links,
            "forms": forms,
            "has_404": "404" in driver.page_source or "not found" in driver.page_source.lower()
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/api/explore", methods=["POST"])
def explore_site():
    """Explore the site structure to find job listings"""
    data = request.json
    session_id = data.get("session_id")
    
    if not session_id or session_id not in sessions:
        return jsonify({"error": "Invalid session"}), 403
    
    driver = sessions[session_id]["driver"]
    
    try:
        # Start from homepage
        driver.get("https://www.iimjobs.com")
        time.sleep(3)
        
        # Find all navigation links
        nav_structure = {}
        
        # Look for main navigation
        nav_selectors = ["nav", ".nav", ".navigation", ".menu", "header"]
        
        for selector in nav_selectors:
            try:
                nav_elements = driver.find_elements(By.CSS_SELECTOR, selector)
                for nav in nav_elements:
                    links = nav.find_elements(By.TAG_NAME, "a")
                    for link in links:
                        text = link.text.strip()
                        href = link.get_attribute("href")
                        if text and href and ("job" in text.lower() or "browse" in text.lower() or "search" in text.lower()):
                            nav_structure[text] = href
            except:
                continue
        
        # Also look for any links containing job-related keywords
        all_links = driver.find_elements(By.TAG_NAME, "a")
        job_related_links = {}
        
        for link in all_links:
            text = link.text.strip()
            href = link.get_attribute("href")
            if href and any(keyword in text.lower() for keyword in ["job", "career", "search", "browse", "find"]):
                job_related_links[text] = href
        
        return jsonify({
            "current_url": driver.current_url,
            "navigation_structure": nav_structure,
            "job_related_links": job_related_links,
            "total_links_found": len(all_links)
        })
        
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/api/job-details", methods=["POST"])
def get_job_details():
    data = request.json
    session_id = data.get("session_id")
    job_url = data.get("job_url")
    job_id = data.get("job_id")  # Alternative to job_url
    
    if not session_id or session_id not in sessions:
        return jsonify({"error": "Invalid session. Please login first."}), 403
    
    if not job_url and not job_id:
        return jsonify({"error": "Either job_url or job_id is required"}), 400

    session_data = sessions[session_id]
    driver = session_data["driver"]

    try:
        wait = WebDriverWait(driver, 15)
        
        # If job_id is provided, construct the URL
        if job_id and not job_url:
            job_url = f"https://www.iimjobs.com/job/{job_id}"
        
        print(f"Fetching job details from: {job_url}")
        
        # Navigate to the job details page
        driver.get(job_url)
        time.sleep(3)
        
        # Wait for page to load
        wait.until(EC.presence_of_element_located((By.TAG_NAME, "body")))
        
        job_details = extract_complete_job_details(driver)
        
        if job_details:
            return jsonify({
                "job_details": job_details,
                "status": "success",
                "url": driver.current_url
            }), 200
        else:
            return jsonify({
                "error": "Failed to extract job details",
                "url": driver.current_url,
                "page_title": driver.title
            }), 404
            
    except Exception as e:
        return jsonify({
            "error": f"Failed to fetch job details: {str(e)}",
            "url": job_url if 'job_url' in locals() else "unknown"
        }), 500

def extract_complete_job_details(driver):
    from selenium.webdriver.common.by import By

    job_details = {}

    def safe_get_text(selectors):
        for selector in selectors:
            try:
                element = driver.find_element(By.CSS_SELECTOR, selector)
                if element:
                    return element.text.strip()
            except:
                continue
        return None

    try:
        # Title
        job_details["title"] = safe_get_text([
            "div.job-header h1",
            "h1"
        ])

        # Experience & Location (from header spans)
        spans = driver.find_elements(By.CSS_SELECTOR, "div.job-header span")
        if len(spans) >= 2:
            job_details["experience"] = spans[0].text.strip()
            job_details["location"] = spans[1].text.strip()

        # Skills
        tags = []
        tag_elements = driver.find_elements(By.CSS_SELECTOR, "div.job-header + div span")
        for tag in tag_elements:
            text = tag.text.strip()
            if text.startswith("#"):
                tags.append(text)
        job_details["skills"] = tags

        # --- ✅ MAIN JOB DESCRIPTION (XPath-based extraction) ---
        jd_paragraphs = driver.find_elements(By.XPATH, '//div[contains(@class, "MuiPaper-root")]//p')
        jd_text = "\n".join([p.text.strip() for p in jd_paragraphs if p.text.strip()])
        if jd_text:
            job_details["description"] = jd_text

        # --- ✅ Extract Requirements as bullet points ---
        bullet_elements = driver.find_elements(By.XPATH, '//div[contains(@class, "MuiPaper-root")]//li')
        requirements = [li.text.strip() for li in bullet_elements if li.text.strip()]
        if requirements:
            job_details["requirements"] = requirements

        # --- ✅ Apply / Save buttons ---
        apply_btn = driver.find_elements(By.XPATH, "//button[contains(., 'Apply')]")
        save_btn = driver.find_elements(By.XPATH, "//button[contains(., 'Save')]")

        save_text = save_btn[0].get_attribute("textContent").strip() if save_btn else ""
        if not save_text:
            save_text = save_btn[0].get_attribute("aria-label") if save_btn else ""

        job_details["application_info"] = {
            "can_apply": len(apply_btn) > 0,
            "can_save": len(save_btn) > 0,
            "apply_button_text": apply_btn[0].text.strip() if apply_btn else None,
            "save_button_text": save_text or None
        }

        # URL
        job_details["job_url"] = driver.current_url

        return {k: v for k, v in job_details.items() if v}

    except Exception as e:
        print(f"[ERROR] while extracting job: {str(e)}")
        return None

def safe_get_text(driver, selectors):
    """Safely get text from multiple possible selectors"""
    for selector in selectors:
        try:
            elements = driver.find_elements(By.CSS_SELECTOR, selector)
            if elements:
                text = elements[0].get_attribute("textContent").strip()
                if text:
                    return text
        except:
            continue
    return None

@app.route("/api/apply-job", methods=["POST"])
def apply_to_job():
    """Apply to a job directly through the app and submit review"""
    data = request.json
    session_id = data.get("session_id")
    job_url = data.get("job_url")

    if not session_id or session_id not in sessions:
        return jsonify({"error": "Invalid session. Please login first."}), 403

    if not job_url:
        return jsonify({"error": "job_url is required"}), 400

    session_data = sessions[session_id]
    driver = session_data["driver"]

    try:
        wait = WebDriverWait(driver, 15)

        # Navigate to job page
        if driver.current_url != job_url:
            driver.get(job_url)
            time.sleep(3)

        # Step 1: Click "Apply" button
        try:
            apply_button = wait.until(EC.element_to_be_clickable((By.XPATH, "//button[contains(text(),'Apply')]")))
            driver.execute_script("arguments[0].click();", apply_button)
            time.sleep(3)
        except Exception as e:
            return jsonify({
                "status": "failed",
                "message": "Could not find or click apply button",
                "current_url": driver.current_url
            }), 400

        # Step 2: Check for form marker
        try:
            form_marker = driver.find_element(By.XPATH, "//*[contains(text(),'Before you submit your application, tell the recruiter more about yourself')]")
            if form_marker:
                form_questions = set()
                try:
                    form_blocks = driver.find_elements(By.XPATH, "//div[contains(@class, 'MuiBox-root')]")
                    for block in form_blocks:
                        try:
                            text = block.text.strip()
                            # Only keep blocks that seem like actual questions
                            if (
                                text
                                and len(text.split()) > 3
                                and "Submit" not in text
                                and "Review" not in text
                                and "Posted by" not in text
                                and "Yrs" not in text
                                and "Apply" not in text
                                and not text.startswith("You are Applying")
                            ):
                                form_questions.add(text)
                        except:
                            continue
                except:
                    pass

                return jsonify({
                    "status": "form_present",
                    "message": "Form detected before review",
                    "current_url": driver.current_url,
                    "form_questions": list(form_questions)
                }), 200
        except:
            pass  # form marker not found

        # Step 3: Check if it's a review screen
        try:
            wait.until(EC.presence_of_element_located(
                (By.XPATH, "//*[contains(text(),'Review your Application') or contains(text(),'You are Applying to') or contains(text(),'You’re applying to')]")))
            return complete_review_and_submit(driver, wait)
        except:
            pass

        return jsonify({
            "status": "partial_success",
            "message": "No form or review screen detected",
            "current_url": driver.current_url
        }), 206

    except Exception as e:
        return jsonify({
            "status": "error",
            "message": f"Application failed: {str(e)}",
            "current_url": driver.current_url if driver else "unknown"
        }), 500

def complete_review_and_submit(driver, wait):
    time.sleep(2)

    def safe_text(xpath):
        try:
            return driver.find_element(By.XPATH, xpath).text.strip()
        except:
            return ""

    review_data = {
        "job_title": safe_text("//h2[contains(text(), 'You are Applying to') or contains(text(),'You are applying to') or contains(text(),'You’re Applying to') or contains(text(),'You’re applying to') or contains(text(),'You are applying')"),
        "resume": safe_text("//div[contains(@class,'MuiBox-root') and .//h6[contains(text(),'Resume')]]"),
        "personal_details": safe_text("//div[contains(@class,'MuiBox-root') and .//h6[contains(text(),'Personal Details')]]"),
        "education": safe_text("//div[contains(@class,'MuiBox-root') and .//h6[contains(text(),'Education')]]"),
        "experience": safe_text("//div[contains(@class,'MuiBox-root') and .//h6[contains(text(),'Work Experience')]]"),
        "notice_period": safe_text("//div[contains(@class,'MuiBox-root') and .//h6[contains(text(),'Notice Period')]]")
    }

    try:
        submit_button = wait.until(
            EC.element_to_be_clickable(
                (By.XPATH, "//button[contains(text(),'Review & Submit') or contains(text(),'Submit') or contains(text(),'Send Application')]")))
        if submit_button.is_displayed() and submit_button.is_enabled():
            driver.execute_script("arguments[0].click();", submit_button)
            time.sleep(2)
            submitted = True
        else:
            submitted = False
    except Exception as e:
        print(f"Submit button not found: {e}")
        submitted = False

    return jsonify({
        "status": "success" if submitted else "partial_success",
        "message": "Application submitted and review submitted" if submitted else "Review page loaded but not submitted",
        "current_url": driver.current_url,
        "review_data": review_data
    }), 200 if submitted else 206

@app.route("/api/fill-form", methods=["POST"])
def submit_form_answers():
    data = request.json
    session_id = data.get("session_id")
    job_url = data.get("job_url")
    form_answers = data.get("form_answers")

    if not session_id or session_id not in sessions:
        return jsonify({"error": "Invalid session. Please login first."}), 403
    if not job_url:
        return jsonify({"error": "job_url is required"}), 400
    if not form_answers or not isinstance(form_answers, list):
        return jsonify({"error": "form_answers must be a list"}), 400

    session_data = sessions[session_id]
    driver = session_data["driver"]
    wait = WebDriverWait(driver, 15)

    try:
        if driver.current_url != job_url:
            driver.get(job_url)
            time.sleep(3)

        filled_count = 0
        combined_answer = form_answers[0].strip().lower()

        # Try to find and click Yes/No using label->input or aria-label
        try:
            yes_xpath = "//label[contains(., 'Yes')]/following::input[@type='radio' or @type='checkbox'][1]"
            no_xpath = "//label[contains(., 'No')]/following::input[@type='radio' or @type='checkbox'][1]"

            if "yes" in combined_answer:
                yes_input = driver.find_element(By.XPATH, yes_xpath)
                driver.execute_script("arguments[0].click();", yes_input)
                filled_count += 1
            elif "no" in combined_answer:
                no_input = driver.find_element(By.XPATH, no_xpath)
                driver.execute_script("arguments[0].click();", no_input)
                filled_count += 1
        except Exception as e:
            print(f"[Checkbox Field] Error: {e}")

        # Try to find any input or textarea field and type answer
        try:
            input_field = None
            try:
                input_field = driver.find_element(By.TAG_NAME, "textarea")
            except:
                try:
                    input_field = driver.find_element(By.XPATH, "//input[@type='text' or not(@type)]")
                except:
                    pass

            if input_field:
                driver.execute_script("arguments[0].scrollIntoView(true);", input_field)
                input_field.clear()
                input_field.send_keys(combined_answer)
                filled_count += 1
        except Exception as e:
            print(f"[Text Field] Error: {e}")

        print(f"Filled {filled_count} fields")

        # Wait for the submit/next/review button
        try:
            submit_button = wait.until(
                EC.element_to_be_clickable(
                    (By.XPATH, "//button[contains(.,'Next') or contains(.,'Review') or contains(.,'Submit')]")
                )
            )
            driver.execute_script("arguments[0].click();", submit_button)
            time.sleep(3)
        except Exception as e:
            print(f"[Submit Button] Error waiting for clickability: {e}")

        return complete_review_and_submit(driver, wait)

    except Exception as e:
        return jsonify({
            "status": "error",
            "message": f"Form submission failed: {str(e)}",
            "current_url": driver.current_url
        }), 500

# Add this function for debugging element visibility
def debug_page_elements(driver):
    print("=== PAGE DEBUG INFO ===")
    print(f"Current URL: {driver.current_url}")
    print(f"Page title: {driver.title}")
    
    # Find all form elements
    inputs = driver.find_elements(By.TAG_NAME, "input")
    textareas = driver.find_elements(By.TAG_NAME, "textarea")
    buttons = driver.find_elements(By.TAG_NAME, "button")
    
    print(f"Found {len(inputs)} input elements")
    print(f"Found {len(textareas)} textarea elements") 
    print(f"Found {len(buttons)} button elements")
    
    # Print button texts
    for i, button in enumerate(buttons):
        try:
            print(f"Button {i}: '{button.text}' - enabled: {button.is_enabled()}")
        except:
            pass

@app.route("/api/save-job", methods=["POST"])
def save_job():
    """Save a job for later through the app"""
    data = request.json
    session_id = data.get("session_id")
    job_url = data.get("job_url")
    
    if not session_id or session_id not in sessions:
        return jsonify({"error": "Invalid session. Please login first."}), 403
    
    if not job_url:
        return jsonify({"error": "job_url is required"}), 400

    session_data = sessions[session_id]
    driver = session_data["driver"]

    try:
        # Navigate to job page if not already there
        if driver.current_url != job_url:
            driver.get(job_url)
            time.sleep(3)
        
        # Find and click save button
        save_selectors = [
            "button:contains('Save')",
            ".save-btn",
            "[class*='save']",
            "input[value*='Save']",
            "a[href*='save']"
        ]
        
        saved = False
        for selector in save_selectors:
            try:
                save_buttons = driver.find_elements(By.CSS_SELECTOR, selector)
                for button in save_buttons:
                    if 'save' in button.get_attribute("textContent").lower():
                        if not button.get_attribute("disabled"):
                            driver.execute_script("arguments[0].click();", button)
                            saved = True
                            time.sleep(2)
                            break
                if saved:
                    break
            except:
                continue
        
        if saved:
            return jsonify({
                "status": "success",
                "message": "Job saved successfully",
                "current_url": driver.current_url
            }), 200
        else:
            return jsonify({
                "status": "failed",
                "message": "Could not find or click save button",
                "current_url": driver.current_url
            }), 400
            
    except Exception as e:
        return jsonify({
            "status": "error",
            "message": f"Save job failed: {str(e)}",
            "current_url": driver.current_url if driver else "unknown"
        }), 500

@app.route("/")
def home():
    return "✅ IIMJobs API is running"


if __name__ == "__main__":
    print("Flask server is starting...")
    app.run(debug=True, host='0.0.0.0', port=5000)


