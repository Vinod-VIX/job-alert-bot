```mermaid
flowchart TD
    A[/User sends /start/] --> B{Chat ID in subscribers?}
    
    B -- No --> C[/Add as Free subscriber/]
    B -- Yes --> D[/Already subscribed/]
    
    C --> E[/Send ✅ Subscribed message/]
    D --> F[/Send ℹ️ Already subscribed message/]
    
    E --> G[/Send Free Plan teaser text/]
    F --> H[/Send Free Plan teaser text/]
    
    G --> I[/User can request jobs /resendall/]
    H --> I
    
    I --> J{Is user Premium?}
    
    J -- No --> K[/Send limited jobs + teaser always/]
    J -- Yes --> L[/Send all jobs, no teaser/]
    
    K --> M[/User can upgrade → /subscribe → UPI → Admin approves → Premium/]
    L --> M
