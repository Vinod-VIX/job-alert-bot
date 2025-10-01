```mermaid
flowchart TD
    %% Define styles
    classDef free fill:#FFD580,stroke:#FFA500,color:#000,font-weight:bold;
    classDef premium fill:#90EE90,stroke:#008000,color:#000,font-weight:bold;
    classDef admin fill:#ADD8E6,stroke:#0000FF,color:#000,font-weight:bold;

    %% Start
    A[/User sends /start/] --> B{Chat ID in subscribers?}

    %% Free user path
    B -- No --> C[/Add as Free subscriber/]
    C --> E[/Send ✅ Subscribed message/]
    E --> G[/Send Free Plan teaser text/]
    G --> I[/User can request jobs /resendall/]

    B -- Yes --> D[/Already subscribed/]
    D --> F[/Send ℹ️ Already subscribed message/]
    F --> H[/Send Free Plan teaser text/]
    H --> I

    %% Job sending
    I --> J{Is user Premium?}

    J -- No --> K[/Send limited jobs + teaser always/]
    class K,G,H free;

    J -- Yes --> L[/Send all jobs, no teaser/]
    class L premium;

    %% Upgrade path
    K --> M[/User can upgrade → /subscribe → UPI → Admin approves → Premium/]
    L --> M

    %% Admin approval
    M --> N[/Admin adds Premium/]
    class N admin;
