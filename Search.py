import os
import requests
import json
import time
import logging
import random
from typing import Dict, List, Any, Optional
from dataclasses import dataclass
from bs4 import BeautifulSoup
from urllib.parse import quote_plus
from tenacity import retry, stop_after_attempt, wait_exponential
from datetime import datetime
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
import os
import json
import logging
import undetected_chromedriver as uc
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException
from groq import Groq
# Initialize FastAPI app and logger
app = FastAPI()
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler("job_scraper.log"),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger("JobScraper")


# ==================== LINKEDIN SCRAPER ====================

class LinkedInJobScraper:
    def __init__(self):
        self.logger = logging.getLogger("LinkedIn")

        self.base_url = "https://www.linkedin.com/jobs/search"

        # Updated experience map with more detailed information
        self.experience_map = {
            "1": {"level": "Internship", "years": "0-1 years"},
            "2": {"level": "Entry level", "years": "0-2 years"},
            "3": {"level": "Associate", "years": "2-3 years"},
            "4": {"level": "Mid-Senior level", "years": "3-8 years"},
            "5": {"level": "Director", "years": "8+ years"},
            "6": {"level": "Executive", "years": "10+ years"}
        }

        self.job_type_map = {
            "onsite": "1",
            "remote": "2",
            "hybrid": "3"
        }

        self.headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.5",
            "Accept-Encoding": "gzip, deflate, br",
            "DNT": "1",
            "Connection": "keep-alive",
            "Upgrade-Insecure-Requests": "1",
            "Sec-Fetch-Dest": "document",
            "Sec-Fetch-Mode": "navigate",
            "Sec-Fetch-Site": "none",
            "Sec-Fetch-User": "?1",
            "Cache-Control": "max-age=0"
        }

    def _encode_params(self, params: Dict) -> str:
        return "&".join([f"{k}={quote_plus(str(v))}" for k, v in params.items() if v])

    def _map_experience_level(self, years: str) -> str:
        try:
            years_num = float(years.split()[0])
            if years_num <= 1:
                return "1"  # Internship
            elif years_num <= 2:
                return "2"  # Entry level
            elif years_num <= 3:
                return "3"  # Associate
            elif years_num <= 8:
                return "4"  # Mid-Senior level
            else:
                return "5"  # Director
        except:
            return "3"  # Default to associate level

    def _get_experience_info(self, exp_level: str) -> Dict:
        """Get detailed experience information"""
        return self.experience_map.get(exp_level, {
            "level": "Not specified",
            "years": "Not specified"
        })

    def _build_search_url(self, criteria: Dict) -> tuple:
        """Build search URL with parameters and return URL and experience level"""
        exp_level = self._map_experience_level(criteria.get("experience", "2 years"))
        params = {
            "keywords": criteria.get("position", ""),
            "location": criteria.get("location", ""),
            "f_E": exp_level,
            "f_WT": self.job_type_map.get(criteria.get("jobNature", "onsite").lower(), "1"),
            "pageNum": "0",
            "start": "0"
        }

        encoded_params = self._encode_params(params)
        return f"{self.base_url}/?{encoded_params}", exp_level

    def _extract_job_data(self, job_element, exp_level: str, criteria: Dict) -> Optional[Dict]:
        """Extract job data from a single job card element"""
        try:
            link_element = job_element.find("a", class_="base-card__full-link")
            if not link_element:
                return None

            # Get experience information
            experience_info = self._get_experience_info(exp_level)

            job_data = {
                "title": link_element.get_text(strip=True),
                "link": link_element.get("href", "").split("?")[0],
                "company": "",
                "location": "",
                "job_id": "",
                "source": "LinkedIn",
                "experience_level": experience_info["level"],
                "experience_years": experience_info["years"],
                "job_nature": criteria.get("jobNature", ""),
                "posted_date": "",
                "salary": criteria.get("salary", "Not specified")
            }

            # Extract company name
            company_element = job_element.find("h4", class_="base-search-card__subtitle")
            if company_element:
                job_data["company"] = company_element.get_text(strip=True)

            # Extract location
            location_element = job_element.find("span", class_="job-search-card__location")
            if location_element:
                job_data["location"] = location_element.get_text(strip=True)

            # Extract job ID
            if job_data["link"]:
                job_id = job_data["link"].split("/")[-1]
                job_data["job_id"] = job_id

            # Try to extract posting date
            date_element = job_element.find("time", class_="job-search-card__listdate")
            if date_element:
                job_data["posted_date"] = date_element.get_text(strip=True)

            return job_data
        except Exception as e:
            self.logger.error(f"Error extracting job data: {str(e)}")
            return None

    def _get_job_description(self, job_url: str) -> Dict:
        """Fetch detailed job description and criteria from job page"""
        try:
            response = requests.get(job_url, headers=self.headers, timeout=10)
            response.raise_for_status()
            soup = BeautifulSoup(response.text, 'html.parser')

            details = {
                "description": "",
                "job_criteria": {}
            }

            # Get job description from show-more-less section
            description_div = soup.find("div", class_="show-more-less-html__markup")
            if description_div:
                details["description"] = description_div.get_text(strip=True)

            # Get job criteria list
            criteria_list = soup.find("ul", class_="description__job-criteria-list")
            if criteria_list:
                criteria_items = criteria_list.find_all("li", class_="description__job-criteria-item")
                for item in criteria_items:
                    header = item.find("h3", class_="description__job-criteria-subheader")
                    value = item.find("span", class_="description__job-criteria-text")

                    if header and value:
                        header_text = header.get_text(strip=True)
                        value_text = value.get_text(strip=True)
                        details["job_criteria"][header_text] = value_text

            return details

        except Exception as e:
            self.logger.error(f"Error fetching job description from {job_url}: {str(e)}")
            return {"description": "", "job_criteria": {}}

    def search_jobs(self, criteria: Dict, max_results: int = 25) -> List[Dict]:
        jobs_found = []
        page = 0

        try:
            self.logger.info(
                f"Starting LinkedIn job search for {criteria.get('position')} in {criteria.get('location')}")

            while len(jobs_found) < max_results:
                # Get URL and experience level
                url, exp_level = self._build_search_url(criteria)
                if page > 0:
                    url += f"&start={page * 25}"

                self.logger.info(f"Fetching page {page + 1} from LinkedIn...")

                # Make request with retry mechanism
                max_retries = 3
                for attempt in range(max_retries):
                    try:
                        response = requests.get(url, headers=self.headers, timeout=10)
                        response.raise_for_status()
                        break
                    except requests.RequestException as e:
                        if attempt == max_retries - 1:
                            self.logger.error(f"Failed to fetch results after {max_retries} attempts: {str(e)}")
                            return jobs_found
                        time.sleep(2 ** attempt)

                soup = BeautifulSoup(response.text, 'html.parser')
                job_cards = soup.find_all("div", class_="base-card")

                if not job_cards:
                    self.logger.info("No more jobs found on LinkedIn.")
                    break

                for job_card in job_cards:
                    job_data = self._extract_job_data(job_card, exp_level, criteria)
                    if job_data:
                        # Fetch detailed job description
                        self.logger.info(f"Fetching description for job: {job_data['title']}")
                        job_details = self._get_job_description(job_data['link'])

                        # Merge job details with job data
                        job_data.update(job_details)

                        # Standardize field names for merging
                        job_data["job_title"] = job_data.pop("title")
                        job_data["apply_link"] = job_data.pop("link")
                        job_data["experience"] = job_data.pop("experience_years")

                        jobs_found.append(job_data)
                        if len(jobs_found) >= max_results:
                            break

                        # Add delay between job detail requests
                        time.sleep(1)

                if len(job_cards) < 25:
                    break

                page += 1
                time.sleep(1)

        except Exception as e:
            self.logger.error(f"Error during LinkedIn job search: {str(e)}")

        self.logger.info(f"LinkedIn search completed. Found {len(jobs_found)} jobs.")
        return jobs_found[:max_results]


# ==================== INDEED SCRAPER ====================

class IndeedScraper:
    def __init__(self):


        self.logger = logging.getLogger("Indeed")
        self.base_url = "https://pk.indeed.com"
        self.setup_driver()

    def setup_driver(self):
        """Initialize undetected-chromedriver"""
        options = uc.ChromeOptions()
        options.add_argument('--no-sandbox')
        options.add_argument('--disable-gpu')
        options.add_argument('--disable-notifications')
        options.add_argument('--disable-popup-blocking')
        options.add_argument('--disable-dev-shm-usage')
        options.add_argument('--disable-extensions')
        try:
            self.driver = uc.Chrome(options=options)
            self.driver.maximize_window()
        except Exception as e:
            self.logger.error(f"Failed to initialize Chrome driver: {e}")
            self.driver = None

    def build_search_url(self, criteria: dict) -> str:
        """Build Indeed search URL with parameters"""
        # Base search URL with position and location
        search_url = f"{self.base_url}/jobs?"

        # Add position
        position = criteria.get('position', '').replace(' ', '+')
        search_url += f"q={position}"

        # Add location
        location = criteria.get('location', '').replace(' ', '+')
        search_url += f"&l={location}"

        # Add job nature (onsite/remote)
        job_nature = criteria.get('jobNature', '').lower()
        if job_nature == 'onsite':
            search_url += "&sc=0kf%3Ajt(fulltime)%3B"
        elif job_nature == 'remote':
            search_url += "&sc=0kf%3Aattr(DSQF7)%3B"

        self.logger.info(f"Built Indeed search URL: {search_url}")
        return search_url

    def extract_job_data(self, job_card, criteria):
        """Extract data from a single job card"""
        try:
            job_data = {
                'job_title': '',
                'company': '',
                'location': '',
                'salary': criteria.get('salary', 'Not specified'),
                'jobNature': criteria.get('jobNature', 'Not specified'),
                'posting_date': '',
                'apply_link': '',
                'source': 'Indeed',
                'experience': criteria.get('experience', 'Not specified')
            }

            # Extract title and link
            title_elem = job_card.find_element(By.CSS_SELECTOR, 'h2.jobTitle')
            if title_elem:
                job_data['job_title'] = title_elem.text.strip()
                link_elem = title_elem.find_element(By.TAG_NAME, 'a')
                if link_elem:
                    job_data['apply_link'] = link_elem.get_attribute('href')

            # Extract company name
            try:
                company_elem = job_card.find_element(By.CSS_SELECTOR, '[data-testid="company-name"]')
                job_data['company'] = company_elem.text.strip()
            except:
                pass

            # Extract location
            try:
                location_elem = job_card.find_element(By.CSS_SELECTOR, 'div.companyLocation')
                job_data['location'] = location_elem.text.strip()
            except:
                pass

            # Extract salary if available
            try:
                salary_elem = job_card.find_element(By.CSS_SELECTOR, 'div.salary-snippet')
                job_data['salary'] = salary_elem.text.strip()
            except:
                pass

            # Extract posting date
            try:
                date_elem = job_card.find_element(By.CSS_SELECTOR, 'span.date')
                job_data['posting_date'] = date_elem.text.strip()
            except:
                pass

            return job_data

        except Exception as e:
            self.logger.error(f"Error extracting Indeed job data: {e}")
            return None

    def get_job_description(self, job_url):
        """Get detailed job description"""
        try:
            self.driver.execute_script("window.open('');")
            self.driver.switch_to.window(self.driver.window_handles[-1])
            self.driver.get(job_url)

            # Wait for job description to load
            description_elem = WebDriverWait(self.driver, 10).until(
                EC.presence_of_element_located((By.ID, "jobDescriptionText"))
            )
            description = description_elem.text.strip()

            self.driver.close()
            self.driver.switch_to.window(self.driver.window_handles[0])

            return description
        except Exception as e:
            self.logger.error(f"Error getting Indeed job description: {e}")
            if len(self.driver.window_handles) > 1:
                self.driver.close()
                self.driver.switch_to.window(self.driver.window_handles[0])
            return ""

    def search_jobs(self, criteria: dict, num_pages: int = 1):


        all_jobs = []

        try:
            url = self.build_search_url(criteria)
            self.logger.info(f"Starting Indeed job search at URL: {url}")

            self.driver.get(url)
            time.sleep(3)  # Wait for initial page load

            for page in range(num_pages):
                self.logger.info(f"Scraping Indeed page {page + 1}...")

                # Wait for job cards to load
                try:
                    job_cards = WebDriverWait(self.driver, 10).until(
                        EC.presence_of_all_elements_located((By.CSS_SELECTOR, "div.job_seen_beacon"))
                    )
                except TimeoutException:
                    self.logger.warning("No job cards found on this Indeed page")
                    break

                # Process each job card
                for card in job_cards:
                    job_data = self.extract_job_data(card, criteria)
                    if job_data:
                        # Get detailed description
                        if job_data['apply_link']:
                            description = self.get_job_description(job_data['apply_link'])
                            job_data['description'] = description
                        all_jobs.append(job_data)
                        self.logger.info(f"Found Indeed job: {job_data['job_title']} at {job_data['company']}")

                # Try to click next page
                try:
                    next_button = self.driver.find_element(By.CSS_SELECTOR, '[aria-label="Next Page"]')
                    if not next_button.is_enabled():
                        break
                    next_button.click()
                    time.sleep(random.uniform(2, 4))
                except:
                    self.logger.info("No more Indeed pages available")
                    break

        except Exception as e:
            self.logger.error(f"Error during Indeed job search: {e}")

        self.logger.info(f"Indeed search completed. Found {len(all_jobs)} jobs.")
        return all_jobs

    def close(self):
        """Close the driver"""
        if hasattr(self, 'driver') and self.driver:
            self.driver.quit()


# ==================== GLASSDOOR SCRAPER ====================

class GlassdoorScraper:
    def __init__(self):


        self.logger = logging.getLogger("Glassdoor")
        self.base_url = "https://www.glassdoor.com/Job"
        self.setup_driver()

    def setup_driver(self):
        """Initialize undetected-chromedriver"""
        options = uc.ChromeOptions()
        options.add_argument('--no-sandbox')
        options.add_argument('--window-size=1920,1080')
        options.add_argument('--disable-gpu')
        options.add_argument('--disable-dev-shm-usage')
        options.add_argument('--disable-extensions')
        try:
            self.driver = uc.Chrome(options=options)
        except Exception as e:
            self.logger.error(f"Failed to initialize Chrome driver: {e}")
            self.driver = None

    def search_and_get_links(self, position: str, location: str):
        """First phase: Search and collect all job links with basic info"""
        if not self.driver:
            return []

        try:
            self.logger.info("Opening Glassdoor Jobs...")
            self.driver.get(self.base_url)
            time.sleep(5)

            self.logger.info(f"Entering position: {position}")
            position_input = WebDriverWait(self.driver, 10).until(
                EC.presence_of_element_located((By.ID, "searchBar-jobTitle"))
            )
            position_input.clear()
            position_input.send_keys(position)
            time.sleep(2)

            self.logger.info(f"Entering location: {location}")
            location_input = WebDriverWait(self.driver, 10).until(
                EC.presence_of_element_located((By.ID, "searchBar-location"))
            )
            location_input.clear()
            location_input.send_keys(location)
            time.sleep(2)

            location_input.send_keys(Keys.RETURN)
            time.sleep(5)

            job_links = []
            try:
                # Find all job cards
                job_cards = self.driver.find_elements(By.CSS_SELECTOR, "a.JobCard_jobTitle__GLyJ1")
                self.logger.info(f"Found {len(job_cards)} Glassdoor job listings")

                for card in job_cards:
                    try:
                        parent_card = card.find_element(By.XPATH, "./../../..")  # Go up to main card container

                        # Extract basic information
                        job_data = {
                            "job_title": card.text.strip(),
                            "apply_link": card.get_attribute("href"),
                            "company": "",
                            "location": "",
                            "description": "",
                            "source": "Glassdoor"
                        }

                        # Extract company name
                        try:
                            company_elem = parent_card.find_element(
                                By.CSS_SELECTOR,
                                "span.EmployerProfile_compactEmployerName__9MGcV"
                            )
                            job_data["company"] = company_elem.text.strip()
                        except:
                            pass

                        # Extract location
                        try:
                            location_elem = parent_card.find_element(
                                By.CSS_SELECTOR,
                                "div.JobCard_location__Ds1fM"
                            )
                            job_data["location"] = location_elem.text.strip()
                        except:
                            pass

                        # Try to get salary if available
                        try:
                            salary = parent_card.find_element(
                                By.CSS_SELECTOR,
                                "div.JobCard_salaryEstimate__QpbTW"
                            ).text.strip()
                            job_data["salary"] = salary
                        except:
                            job_data["salary"] = "Not specified"

                        # Try to get easy apply status
                        try:
                            easy_apply = parent_card.find_element(
                                By.CSS_SELECTOR,
                                "div.JobCard_easyApplyTag__5vlo5"
                            ).is_displayed()
                            job_data["easy_apply"] = "Yes" if easy_apply else "No"
                        except:
                            job_data["easy_apply"] = "No"

                        job_links.append(job_data)
                        self.logger.info(
                            f"Collected Glassdoor link for: {job_data['job_title']} at {job_data['company']}")

                    except Exception as e:
                        self.logger.error(f"Error collecting Glassdoor link data: {str(e)}")
                        continue

            except Exception as e:
                self.logger.error(f"Error finding Glassdoor job cards: {str(e)}")

            return job_links

        except Exception as e:
            self.logger.error(f"Error in Glassdoor search_and_get_links: {str(e)}")
            return []

    def get_job_details(self, job_data):
        """Get detailed information for a single job"""
        if not self.driver:
            return job_data

        try:
            self.logger.info(f"Getting Glassdoor details for: {job_data['job_title']} at {job_data['company']}")

            # Open job URL in the current window
            self.driver.get(job_data['apply_link'])
            time.sleep(5)

            try:
                # First, try to click the "Show More" button if it exists
                try:
                    show_more_button = WebDriverWait(self.driver, 5).until(
                        EC.presence_of_element_located((By.CLASS_NAME, "JobDetails_showMoreWrapper__ja2_y"))
                    )
                    show_more_button.click()
                    time.sleep(2)  # Wait for content to expand
                except:
                    # If no show more button, continue with existing content
                    pass

                # Wait for and get the job description
                description_elem = WebDriverWait(self.driver, 10).until(
                    EC.presence_of_element_located((By.CLASS_NAME, "JobDetails_jobDescription__uW_fK"))
                )

                # Get the complete text content, preserving all information
                full_description = description_elem.text.strip()

                # Update job data with the complete description
                job_data['description'] = full_description

                # Try to extract experience
                job_data['experience'] = "Not specified"
                job_data['jobNature'] = "Not specified"
                for term in ["years of experience", "year experience", "years experience"]:
                    if term in full_description.lower():
                        # Look for phrases like "2+ years of experience" or "2-3 years experience"
                        for i in range(15):
                            if f"{i}+" in full_description or f"{i}-" in full_description or f"{i} " in full_description:
                                job_data['experience'] = f"{i} years"
                                break

                # Try to detect job nature
                if "remote" in full_description.lower():
                    job_data['jobNature'] = "remote"
                elif "hybrid" in full_description.lower():
                    job_data['jobNature'] = "hybrid"
                elif "on-site" in full_description.lower() or "onsite" in full_description.lower():
                    job_data['jobNature'] = "onsite"

                return job_data

            except Exception as e:
                self.logger.error(f"Error getting Glassdoor job description: {str(e)}")
                return job_data

        except Exception as e:
            self.logger.error(f"Error accessing Glassdoor job page: {str(e)}")
            return job_data

    def search_jobs(self, criteria: Dict):

        try:
            position = criteria.get("position", "")
            location = criteria.get("location", "")

            # Phase 1: Get all job links with basic info
            self.logger.info("Phase 1: Collecting Glassdoor job links...")
            job_links = self.search_and_get_links(position, location)
            self.logger.info(f"Collected {len(job_links)} Glassdoor job links")

            # Phase 2: Get complete description for each job
            self.logger.info("Phase 2: Getting detailed information for each Glassdoor job...")
            detailed_jobs = []

            for job_data in job_links:
                job_details = self.get_job_details(job_data)
                if job_details:
                    # Add any missing fields from criteria
                    if 'experience' not in job_details or not job_details['experience']:
                        job_details['experience'] = criteria.get('experience', 'Not specified')
                    if 'jobNature' not in job_details or not job_details['jobNature']:
                        job_details['jobNature'] = criteria.get('jobNature', 'Not specified')

                    detailed_jobs.append(job_details)
                time.sleep(2)

            self.logger.info(f"Glassdoor search completed. Found {len(detailed_jobs)} jobs.")
            return detailed_jobs

        except Exception as e:
            self.logger.error(f"Error in Glassdoor scrape_jobs: {str(e)}")
            return []

    def close(self):
        """Close the driver"""
        if hasattr(self, 'driver') and self.driver:
            self.driver.quit()


# ==================== GROQ CLIENT ====================

import logging
import os
import json
import re
from dataclasses import dataclass
from typing import Optional, List, Dict, Any
from tenacity import retry, stop_after_attempt, wait_exponential

# Assuming groq library is installed and available
try:
    from groq import Groq

    GROQ_AVAILABLE = True
except ImportError:
    GROQ_AVAILABLE = False


    class Groq:
        pass

# --- Setup Logger ---
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)


# --- Groq Related Classes ---
class GroqAPIError(Exception):
    """Custom exception for Groq API errors."""
    pass


@dataclass
class GroqConfig:
    model: str = "deepseek-r1-distill-llama-70b"
    temperature: float = 0.5
    max_tokens: int = 8000
    top_p: float = 0.9
    stream: bool = False


class GroqClient:
    def __init__(self, api_key: Optional[str] = None):
        self.logger = logging.getLogger(f"{__name__}.GroqClient")

        if not GROQ_AVAILABLE:
            self.logger.error("Groq library not available. AI job filtering disabled.")
            self.client = None
            self.config = None
            return

        self.api_key = api_key or os.getenv("GROQ_API_KEY")
        if not self.api_key:
            self.logger.error("No API key provided. Set GROQ_API_KEY environment variable or pass key directly.")
            raise ValueError("No API key provided for GroqClient.")

        try:
            self.client = Groq(api_key=self.api_key)
            self.config = GroqConfig()
            self.logger.info(f"GroqClient initialized with model: {self.config.model}")
        except Exception as e:
            self.logger.error(f"Failed to initialize Groq client: {e}", exc_info=True)
            raise

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=4, max=10), reraise=True)
    def get_completion(self, prompt: str, max_tokens: Optional[int] = None) -> str:
        """Sends a prompt to the Groq API and returns the completion."""
        if not self.client or not self.config:
            self.logger.error("GroqClient not properly initialized.")
            raise GroqAPIError("GroqClient not initialized.")

        self.logger.debug(f"Sending prompt to Groq (first 100 chars): {prompt[:100]}...")
        try:
            resp = self.client.chat.completions.create(
                messages=[{"role": "user", "content": prompt}],
                model=self.config.model,
                temperature=self.config.temperature,
                max_tokens=max_tokens or self.config.max_tokens,
                top_p=self.config.top_p,
                stream=False
            )

            # --- Added Logging ---
            self.logger.debug(f"Received response object type: {type(resp)}")
            if hasattr(resp, 'choices') and resp.choices:
                choice = resp.choices[0]
                self.logger.debug(f"Received choice object type: {type(choice)}")
                if hasattr(choice, 'message') and choice.message:
                    message = choice.message
                    self.logger.debug(f"Received message object type: {type(message)}")
                    if hasattr(message, 'content'):
                        content = message.content
                        self.logger.debug(f"Received content type: {type(content)}")
                        if isinstance(content, str):
                            self.logger.debug(f"Received content length: {len(content)}")
                            self.logger.debug(f"Returning completion string (first 100 chars): {content[:100]}...")
                            return content.strip()
                        else:
                            self.logger.error(f"Content is not a string. Type: {type(content)}")
                            self.logger.debug(f"Content value: {content}")
                            raise GroqAPIError(f"Unexpected content type from Groq API: {type(content)}")
                    else:
                        self.logger.error("Message object has no 'content' attribute.")
                        raise GroqAPIError("Message object missing content.")
                else:
                    self.logger.error("Response choice object has no 'message' attribute or message is None.")
                    raise GroqAPIError("Response choice missing message.")
            else:
                self.logger.error(f"Unexpected Groq API response structure or no choices: {resp}")
                raise GroqAPIError("Unexpected response structure or no choices from Groq API.")
            # --- End Added Logging ---

        except Exception as e:
            self.logger.error(f"Error during Groq API request: {e}", exc_info=True)
            if "model_not_found" in str(e).lower():
                self.logger.error(
                    f"Model '{self.config.model}' might not be available or misspelled. Check available models on Groq.")
            raise GroqAPIError(f"API request failed after retries: {e}")

    def search_jobs_batch(self,
                          jobs_data: List[Dict[str, Any]],
                          search_criteria: Dict[str, str],
                          raw_responses_collector: Optional[List[str]] = None
                          ) -> str:
        """
        Processes a batch of jobs against search criteria using the LLM.
        Optionally collects the raw LLM response string into the provided list.
        Returns the raw LLM response string.
        """
        if not self.client or not self.config:
            self.logger.error("GroqClient not properly initialized, cannot search jobs.")
            return ""

        if not jobs_data:
            self.logger.info("Empty job batch received, skipping API call.")
            return ""

        try:
            jobs_json = json.dumps(jobs_data, ensure_ascii=False, indent=2)
            criteria_json = json.dumps(search_criteria, ensure_ascii=False, indent=2)
        except TypeError as e:
            self.logger.error(f"Failed to serialize job data or criteria to JSON: {e}")
            return ""

        prompt = (
            "You are a job-matching assistant. Your task is to filter job listings based on specific criteria.\n"
            "Here is a list of job listings (JSON array):\n"
            f"{jobs_json}\n\n"
            "Here are the search criteria (JSON object):\n"
            f"{criteria_json}\n\n"
            "Analyze the job listings and return a JSON object containing only the jobs that match ALL the provided criteria. If it even matches some criteria of skills approve it.\n"
            "The response MUST be a JSON object with a single key named \"relevant_jobs\". The value of this key must be an array of job objects.\n"
            "Each job object in the array MUST include exactly these fields: job_title, company, experience, jobNature, location, salary, apply_link.\n"
            "Ensure the experience level (e.g., '2 years') and location (e.g., 'Islamabad, Pakistan') are matched appropriately. Consider salary ranges if provided.\n"
            "If a job listing is missing one of the required fields (like 'salary' or 'apply_link'), attempt to infer it, represent it as 'Not Specified' or null, otherwise exclude the job if essential criteria cannot be verified.\n"
            "VERY IMPORTANT: Show your thinking first in a think tag, then respond ONLY with the JSON object. Do NOT include any introductory text, explanations, apologies, or concluding remarks. The JSON response should start with `{` and end with `}`."
        )

        try:
            result_str = self.get_completion(prompt)

            if raw_responses_collector is not None:
                raw_responses_collector.append(result_str)

            return result_str

        except GroqAPIError as e:
            self.logger.error(f"Groq API error during job search: {e}")
            return ""
        except Exception as e:
            self.logger.error(f"An unexpected error occurred during job search: {e}", exc_info=True)
            return ""


def process_job_batches(jobs: List[Dict[str, Any]], batch_size: int = 10, source_identifier: str = "data"):
    """Takes a list of job listings and yields batches."""
    if jobs:
        for i in range(0, len(jobs), batch_size):
            batch = jobs[i:i + batch_size]
            logger.info(f"Yielding batch {i // batch_size + 1} from {source_identifier} (size: {len(batch)})")
            yield batch
    else:
        logger.warning(f"No jobs found from {source_identifier} to process.")
        yield []


def extract_json_from_llm_response(response_text: str) -> Optional[Dict]:
    """
    Extract JSON from LLM response, handling various formats including:
    - JSON after a "think" tag
    - JSON in code blocks (```json ... ```)
    - Direct JSON in the response
    """
    try:
        # Method 1: Look for JSON after <think> tag
        think_match = re.search(r'</think>\s*(.*)', response_text, re.DOTALL)
        if think_match:
            potential_json_text = think_match.group(1).strip()

            # If the text after </think> contains code blocks, extract from those
            code_blocks = re.findall(r'```(?:json)?\s*([\s\S]*?)\s*```', potential_json_text)
            if code_blocks:
                try:
                    return json.loads(code_blocks[0].strip())
                except json.JSONDecodeError:
                    logger.debug("Failed to parse JSON from code block after think tag")

            # Otherwise try to extract JSON directly from the text after </think>
            json_match = re.search(r'({[\s\S]*})', potential_json_text)
            if json_match:
                try:
                    return json.loads(json_match.group(1))
                except json.JSONDecodeError:
                    logger.debug("Failed to parse JSON from text after think tag")

        # Method 2: Look for code blocks with JSON
        code_blocks = re.findall(r'```(?:json)?\s*([\s\S]*?)\s*```', response_text)
        if code_blocks:
            for block in code_blocks:
                try:
                    return json.loads(block.strip())
                except json.JSONDecodeError:
                    continue

        # Method 3: Try to find and parse any JSON-like content in the whole response
        json_match = re.search(r'({[\s\S]*})', response_text)
        if json_match:
            try:
                return json.loads(json_match.group(1))
            except json.JSONDecodeError:
                logger.debug("Failed to parse potential JSON from response")

        # Method 4: Last resort - try to parse the entire response as JSON
        try:
            return json.loads(response_text)
        except json.JSONDecodeError:
            logger.warning("Could not extract valid JSON from response")
            return None

    except Exception as e:
        logger.error(f"Error extracting JSON from response: {e}")
        return None


# Define the input schema
class SearchCriteria(BaseModel):
    position: str
    experience: str
    salary: str
    jobNature: str
    location: str
    skills: str

@app.post("/process_jobs")
async def process_jobs(search_criteria: SearchCriteria):
    try:
        logger.info("Starting job processing...")

        # Scraping jobs
        scraper_linkedin = LinkedInJobScraper()
        jobs1 = scraper_linkedin.search_jobs(search_criteria.dict(), max_results=25)
        logger.info(f"LinkedIn scraper returned {len(jobs1)} jobs.")

        scraper_indeed = IndeedScraper()
        jobs2 = scraper_indeed.search_jobs(search_criteria.dict())
        logger.info(f"Indeed scraper returned {len(jobs2)} jobs.")

        scraper_glassdoor = GlassdoorScraper()
        jobs3 = scraper_glassdoor.search_jobs(search_criteria.dict())
        logger.info(f"Glassdoor scraper returned {len(jobs3)} jobs.")

        all_scraped_jobs = jobs1 + jobs2 + jobs3
        logger.info(f"Total scraped jobs combined: {len(all_scraped_jobs)}")

    except Exception as e:
        logger.error(f"An error occurred during scraping: {e}", exc_info=True)
        all_scraped_jobs = []

    output_file = "combined_job_matches.json"
    raw_output_file = "raw_llm_responses.json"
    batch_size = 3

    all_matches = []
    client = None

    api_key = os.getenv("GROQ_API_KEY")
    if not api_key:
        api_key = "your_groq_api_key"  # Replace with your actual key
        os.environ["GROQ_API_KEY"] = "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"

    raw_llm_responses = []

    try:
        if not os.getenv("GROQ_API_KEY"):
            raise HTTPException(status_code=500, detail="GROQ_API_KEY environment variable not set.")

        client = GroqClient()

        if not client:
            raise HTTPException(status_code=500, detail="GroqClient failed to initialize.")

        if all_scraped_jobs:
            batch_count = 0
            for batch in process_job_batches(all_scraped_jobs, batch_size, source_identifier="scraped_data"):
                batch_count += 1
                try:
                    raw_response_str = client.search_jobs_batch(batch, search_criteria.dict(), raw_responses_collector=raw_llm_responses)

                    if raw_response_str:
                        try:
                            json_data = extract_json_from_llm_response(raw_response_str)

                            if json_data and "relevant_jobs" in json_data:
                                matches = json_data["relevant_jobs"]
                                if isinstance(matches, list):
                                    all_matches.extend(matches)
                                    logger.info(f"Parsed {len(matches)} relevant matches from batch {batch_count}.")
                                else:
                                    logger.warning(f"'relevant_jobs' is not a list in response from batch {batch_count}")
                            else:
                                logger.warning(f"Could not extract valid JSON from batch {batch_count}")
                        except Exception as e:
                            logger.error(f"Error processing response from batch {batch_count}: {e}", exc_info=True)
                    else:
                        logger.warning(f"Empty response string from batch {batch_count}")

                except Exception as e:
                    logger.error(f"Error during Groq API call for batch {batch_count}: {e}", exc_info=True)

        logger.info(f"Job search complete. Total relevant matches: {len(all_matches)}")

        try:
            with open(output_file, 'w', encoding='utf-8') as f:
                json.dump({"relevant_jobs": all_matches}, f, indent=2, ensure_ascii=False)
            logger.info(f"Results saved to: {output_file}")

        except Exception as e:
            logger.error(f"Failed to write results to {output_file}: {e}")

        try:
            if raw_llm_responses:
                with open(raw_output_file, 'w', encoding='utf-8') as f:
                    json.dump(raw_llm_responses, f, indent=2, ensure_ascii=False)
                logger.info(f"Raw LLM responses saved to: {raw_output_file}")

        except Exception as e:
            logger.error(f"Failed to write raw responses to {raw_output_file}: {e}")

        return {"relevant_jobs": all_matches}

    except Exception as e:
        logger.error(f"An unexpected error occurred: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="An error occurred during job processing.")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)