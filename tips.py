"""Short, factual buyer tips shown on Mon/Wed/Fri. No investment advice."""

TIPS = (
    'Hallmark wali jewellery par 6-digit HUID code hota hai. BIS CARE app mein "Verify HUID" se purity aur jeweller check kar sakte hain.',
    'Purity marking yaad rakhein: 24K = 999, 22K = 916, 18K = 750. Ye number hallmark ke saath jewellery par likha hota hai.',
    'Pakka GST bill lein jisme weight, purity (916/750) aur making charge alag-alag likha ho. Exchange ya resale mein yahi kaam aata hai.',
    'Making charge fix nahi hota — dukaan aur design ke hisaab se badalta hai. Do-teen dukaan par per gram making zaroor poochein.',
    'Stone/kundan wali jewellery mein stone ka weight gold ke weight se alag likhwayein, warna stone bhi gold ke rate mein lag jaata hai.',
    'Purana gold exchange karte waqt purity test (karat meter) apne saamne karwayein aur deduction ka percentage pehle se poochein.',
    'Rs 2 lakh se zyada ki jewellery khareedne par PAN dena zaroori hai, aur ek din mein Rs 2 lakh ya usse zyada cash lena dukaan ke liye allowed nahi hai.',
    'Message mein diya rate GST (3%) aur making ke bina hai. Final bill = gold value + making + GST.',
    'Traditional tola = 11.66 gram hota hai, jabki aajkal rate aksar per 10 gram bataya jaata hai. Rate compare karte waqt unit check karein.',
    'Khareedne se pehle dukaan ki buyback/exchange policy likhit mein samajh lein — kitna kat-ta hai, kab tak valid hai.',
)
TIP_DAYS = (0, 2, 4)  # Monday, Wednesday, Friday


def tip_for(day):
    """Tip for this date, or None on non-tip days. Rotates through the list."""
    if day.weekday() not in TIP_DAYS:
        return None
    week = day.isocalendar()[1] + day.isocalendar()[0] * 53
    return TIPS[(week * len(TIP_DAYS) + TIP_DAYS.index(day.weekday())) % len(TIPS)]
