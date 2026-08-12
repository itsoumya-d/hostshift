import json

entries = [
    {
        "id": "ext-001",
        "prompt": "An expense tracker where I can add a transaction with amount and category, and see a list of my latest expenses. I also want to edit them.",
        "source": "reddit r/SideProject",
        "expressible": True,
        "reason": None,
        "category": "list_detail"
    },
    {
        "id": "ext-002",
        "prompt": "A real-time collaborative whiteboard where my team can draw wireframes together and chat.",
        "source": "ProductHunt listing",
        "expressible": False,
        "reason": "requires canvas drawing and real-time collaboration",
        "category": "out_of_scope"
    },
    {
        "id": "ext-003",
        "prompt": "A habit tracker app that lets me check off my daily habits and shows a summary of my progress.",
        "source": "HackerNews Show HN",
        "expressible": True,
        "reason": None,
        "category": "list_detail"
    },
    {
        "id": "ext-004",
        "prompt": "I need a form to collect user feedback, including a rating from 1 to 5, a text comment, and their email address. If they rate 1 or 2, the comment should be mandatory.",
        "source": "StackOverflow question",
        "expressible": True,
        "reason": None,
        "category": "form_validation"
    },
    {
        "id": "ext-005",
        "prompt": "A recipe app where I can view a list of recipes, tap one to see the ingredients, and mark it as a favorite.",
        "source": "reddit r/reactnative",
        "expressible": True,
        "reason": None,
        "category": "list_detail"
    },
    {
        "id": "ext-006",
        "prompt": "A fitness app that connects to my smartwatch via Bluetooth to show my live heart rate during a workout.",
        "source": "freelance job posting",
        "expressible": False,
        "reason": "requires bluetooth and hardware integration",
        "category": "out_of_scope"
    },
    {
        "id": "ext-007",
        "prompt": "A simple todo list where I can add items, toggle their completion status, and clear all completed tasks at once.",
        "source": "reddit r/learnprogramming",
        "expressible": True,
        "reason": None,
        "category": "list_detail"
    },
    {
        "id": "ext-008",
        "prompt": "An app to track my plant watering schedule. It needs a list of plants, and I can press a button to record that I watered a plant today.",
        "source": "app store review",
        "expressible": True,
        "reason": None,
        "category": "list_detail"
    },
    {
        "id": "ext-009",
        "prompt": "A photo editing app with filters, crop, and draw tools to markup images before saving.",
        "source": "reddit r/AppIdeas",
        "expressible": False,
        "reason": "requires canvas drawing and image manipulation",
        "category": "out_of_scope"
    },
    {
        "id": "ext-010",
        "prompt": "A multi-step onboarding wizard for my SaaS. First screen asks for name, second for company size, third for role, then a submit button.",
        "source": "ProductHunt discussion",
        "expressible": True,
        "reason": None,
        "category": "form_validation"
    },
    {
        "id": "ext-011",
        "prompt": "A kanban board where I can drag and drop task cards between 'To Do', 'In Progress', and 'Done' columns.",
        "source": "StackOverflow question",
        "expressible": False,
        "reason": "requires drag-and-drop",
        "category": "out_of_scope"
    },
    {
        "id": "ext-012",
        "prompt": "A simple shopping cart screen that lists items, lets me adjust quantities, shows a total, and has a checkout button.",
        "source": "reddit r/webdev",
        "expressible": True,
        "reason": None,
        "category": "list_detail"
    },
    {
        "id": "ext-013",
        "prompt": "A settings page for my app with toggles for push notifications, email alerts, and a select dropdown for theme (light/dark/system).",
        "source": "freelance job posting",
        "expressible": True,
        "reason": None,
        "category": "settings"
    },
    {
        "id": "ext-014",
        "prompt": "An interactive map application that shows nearby coffee shops with custom pins. Clicking a pin shows store details.",
        "source": "HackerNews Show HN",
        "expressible": False,
        "reason": "requires map widget",
        "category": "out_of_scope"
    },
    {
        "id": "ext-015",
        "prompt": "A basic contact list. I want to see names and phone numbers. Tapping a contact opens a page where I can edit their details.",
        "source": "reddit r/SwiftUI",
        "expressible": True,
        "reason": None,
        "category": "list_detail"
    },
    {
        "id": "ext-016",
        "prompt": "A file manager where I can upload PDFs, preview them in-app, and share links to them.",
        "source": "ProductHunt listing",
        "expressible": False,
        "reason": "requires file upload and PDF rendering",
        "category": "out_of_scope"
    },
    {
        "id": "ext-017",
        "prompt": "A user profile editor that requires entering a first name, last name, and a bio. Bio cannot exceed 200 characters.",
        "source": "StackOverflow question",
        "expressible": True,
        "reason": None,
        "category": "form_validation"
    },
    {
        "id": "ext-018",
        "prompt": "A podcast player app. It needs play/pause controls, a progress scrubber, and background audio support.",
        "source": "reddit r/reactnative",
        "expressible": False,
        "reason": "requires audio playback and background services",
        "category": "out_of_scope"
    },
    {
        "id": "ext-019",
        "prompt": "A simple issue tracker where I can see a list of bugs, filter them by 'open' or 'closed', and add a new bug report.",
        "source": "HackerNews comment",
        "expressible": True,
        "reason": None,
        "category": "list_detail"
    },
    {
        "id": "ext-020",
        "prompt": "A dashboard for my admin panel that shows active users, total revenue, and a list of recent signups.",
        "source": "freelance job posting",
        "expressible": True,
        "reason": None,
        "category": "dashboard"
    },
    {
        "id": "ext-021",
        "prompt": "A stock trading app that shows a live updating candlestick chart for selected tickers.",
        "source": "reddit r/algotrading",
        "expressible": False,
        "reason": "requires complex charts and real-time updates",
        "category": "out_of_scope"
    },
    {
        "id": "ext-022",
        "prompt": "A quiz app where one question is shown at a time. After answering, it immediately shows whether you were right or wrong, then goes to the next question.",
        "source": "reddit r/SideProject",
        "expressible": True,
        "reason": None,
        "category": "form_validation"
    },
    {
        "id": "ext-023",
        "prompt": "An event registration form. If they select 'Student' from a dropdown, a new text field for 'University Name' should appear and become required.",
        "source": "StackOverflow question",
        "expressible": True,
        "reason": None,
        "category": "form_validation"
    },
    {
        "id": "ext-024",
        "prompt": "A Tinder-like dating app where you can swipe left or right on profile cards.",
        "source": "freelance job posting",
        "expressible": False,
        "reason": "requires gesture recognition and swipe animations",
        "category": "out_of_scope"
    },
    {
        "id": "ext-025",
        "prompt": "A simple chat interface with a list of messages and a text input at the bottom to send a new message.",
        "source": "reddit r/webdev",
        "expressible": True,
        "reason": None,
        "category": "list_detail"
    },
    {
        "id": "ext-026",
        "prompt": "An augmented reality furniture placement app that uses the camera to place 3D models in a room.",
        "source": "ProductHunt listing",
        "expressible": False,
        "reason": "requires camera access and AR rendering",
        "category": "out_of_scope"
    },
    {
        "id": "ext-027",
        "prompt": "A task manager that lets me create a task with a title and an optional due date.",
        "source": "reddit r/productivity",
        "expressible": True,
        "reason": None,
        "category": "form_validation"
    },
    {
        "id": "ext-028",
        "prompt": "A data table component that supports clicking on column headers to sort the data ascending or descending.",
        "source": "StackOverflow question",
        "expressible": False,
        "reason": "requires complex tables with sorting",
        "category": "out_of_scope"
    },
    {
        "id": "ext-029",
        "prompt": "An FAQ page with a list of questions. Tapping a question expands it to show the answer.",
        "source": "reddit r/reactnative",
        "expressible": True,
        "reason": None,
        "category": "list_detail"
    },
    {
        "id": "ext-030",
        "prompt": "A password reset flow: first screen takes email, second takes verification code, third takes new password and confirms it.",
        "source": "freelance job posting",
        "expressible": True,
        "reason": None,
        "category": "form_validation"
    },
    {
        "id": "ext-031",
        "prompt": "A video conferencing app with a grid view of participants and controls to mute audio or disable video.",
        "source": "HackerNews Show HN",
        "expressible": False,
        "reason": "requires video streaming and hardware access",
        "category": "out_of_scope"
    },
    {
        "id": "ext-032",
        "prompt": "A simple counter app with 'increment', 'decrement', and 'reset' buttons.",
        "source": "reddit r/learnprogramming",
        "expressible": True,
        "reason": None,
        "category": "dashboard"
    },
    {
        "id": "ext-033",
        "prompt": "A booking app for a barbershop. You select a service from a list, then pick an available date and submit the appointment.",
        "source": "reddit r/SideProject",
        "expressible": True,
        "reason": None,
        "category": "form_validation"
    },
    {
        "id": "ext-034",
        "prompt": "A text editor with rich text formatting like bold, italics, and inserting images into the document.",
        "source": "ProductHunt discussion",
        "expressible": False,
        "reason": "requires rich text editing and file insertion",
        "category": "out_of_scope"
    },
    {
        "id": "ext-035",
        "prompt": "A feedback form with three fields: name, email, and message. All are required before the submit button is enabled.",
        "source": "StackOverflow question",
        "expressible": True,
        "reason": None,
        "category": "form_validation"
    },
    {
        "id": "ext-036",
        "prompt": "An inventory app that lets me scan a barcode using my phone's camera, then fetches the product details.",
        "source": "freelance job posting",
        "expressible": False,
        "reason": "requires camera access for scanning",
        "category": "out_of_scope"
    },
    {
        "id": "ext-037",
        "prompt": "A generic login screen with username and password inputs, a 'Remember Me' checkbox, and a 'Sign In' button.",
        "source": "reddit r/web_design",
        "expressible": True,
        "reason": None,
        "category": "form_validation"
    },
    {
        "id": "ext-038",
        "prompt": "A weather app that shows the current temperature and a 7-day forecast list.",
        "source": "HackerNews Show HN",
        "expressible": True,
        "reason": None,
        "category": "list_detail"
    },
    {
        "id": "ext-039",
        "prompt": "A music making app with a piano keyboard interface that plays sounds when you press the keys.",
        "source": "reddit r/AppIdeas",
        "expressible": False,
        "reason": "requires low-latency audio and custom touch interfaces",
        "category": "out_of_scope"
    },
    {
        "id": "ext-040",
        "prompt": "A feature request board where users can see a list of ideas and click an 'upvote' button next to the ones they like.",
        "source": "reddit r/SaaS",
        "expressible": True,
        "reason": None,
        "category": "list_detail"
    },
    {
        "id": "ext-041",
        "prompt": "A survey form where the second question only appears if they answer 'Yes' to the first question.",
        "source": "StackOverflow question",
        "expressible": True,
        "reason": None,
        "category": "form_validation"
    },
    {
        "id": "ext-042",
        "prompt": "A game where I can draw a picture and other people have to guess what it is.",
        "source": "freelance job posting",
        "expressible": False,
        "reason": "requires canvas drawing",
        "category": "out_of_scope"
    },
    {
        "id": "ext-043",
        "prompt": "A simple timer app where I input minutes and seconds, and it counts down when I press start.",
        "source": "reddit r/learnprogramming",
        "expressible": True,
        "reason": None,
        "category": "dashboard"
    },
    {
        "id": "ext-044",
        "prompt": "A delivery tracking app that shows the driver's current location on a live map.",
        "source": "ProductHunt listing",
        "expressible": False,
        "reason": "requires map widget and live location tracking",
        "category": "out_of_scope"
    },
    {
        "id": "ext-045",
        "prompt": "An admin panel to manage users. I need to see a list of users, and a 'Delete' button next to each one that removes them from the list.",
        "source": "reddit r/reactnative",
        "expressible": True,
        "reason": None,
        "category": "list_detail"
    },
    {
        "id": "ext-046",
        "prompt": "A PDF viewer that lets me highlight text and add sticky notes to specific pages.",
        "source": "HackerNews Show HN",
        "expressible": False,
        "reason": "requires PDF rendering and custom annotations",
        "category": "out_of_scope"
    },
    {
        "id": "ext-047",
        "prompt": "A simple flashcard app. It shows a word, and a 'Show Definition' button that reveals the meaning below it.",
        "source": "reddit r/languagelearning",
        "expressible": True,
        "reason": None,
        "category": "list_detail"
    },
    {
        "id": "ext-048",
        "prompt": "A restaurant menu app with tabs for 'Starters', 'Mains', and 'Desserts'. Each tab shows a list of dishes.",
        "source": "freelance job posting",
        "expressible": True,
        "reason": None,
        "category": "list_detail"
    },
    {
        "id": "ext-049",
        "prompt": "A secure file vault where I can upload sensitive documents, and they are encrypted before being stored.",
        "source": "StackOverflow question",
        "expressible": False,
        "reason": "requires file upload and cryptographic processing",
        "category": "out_of_scope"
    },
    {
        "id": "ext-050",
        "prompt": "A newsletter signup banner with an email input and a subscribe button. If the email is invalid, it shows an error message.",
        "source": "reddit r/webdev",
        "expressible": True,
        "reason": None,
        "category": "form_validation"
    }
]

with open('/Users/soumyadebnath16/Downloads/hostshift 3/tasks/external_corpus.jsonl', 'w') as f:
    for e in entries:
        json.dump(e, f)
        f.write('\n')
