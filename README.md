# Career-Quest
Career Quest is a Fast API based job searcher that takes a json with keys Position, Experience, Salary, Job Nature, Location and Skills as an input and returns all the relevant jobs with their links.

# Data
The data is collected from linkedin, indeed and glassdoor through scraping. Using undetected chrome proved helpful in scraping indeed and glassdoor without getting blocked even once and for linkedin i send url request with my selections and I identified the URL of linkedin can handle choices and selections so i was not blocked and then use bs4 for getting my data.

# LLM Approach
After getting enough data it was feeded to LLM with a structured prompt to filter out relevant jobs according to user's input. Following are the screenshots of data and filtering out jobs.
![Screenshot 2025-04-22 212430](https://github.com/user-attachments/assets/93b9aae0-24e1-4487-a3c6-c527bfba70fd)
![Screenshot 2025-04-22 212446](https://github.com/user-attachments/assets/64cc0bf3-1427-453e-a9cc-af33004e8bd0)
![Screenshot 2025-04-22 212503](https://github.com/user-attachments/assets/849164ad-64ff-41af-9bce-ec3cae12c7c9)
![Screenshot 2025-04-22 213159](https://github.com/user-attachments/assets/8264a314-c686-4306-9818-8c47ccbd067d)
![Screenshot 2025-04-22 213309](https://github.com/user-attachments/assets/051f6e08-38bf-4b9b-8c73-daf4e5379b02)
![Screenshot 2025-04-22 213336](https://github.com/user-attachments/assets/37959030-1b46-4171-90c4-93f337ee3a49)
