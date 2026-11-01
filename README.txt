Crop Recommendation System using Machine Learning

FEATURES
1. Sign Up and Login.
2. User details are automatically stored in a MySQL database.
3. Each new account receives an automatic User ID.
4. Nitrogen, Phosphorus and Potassium are shown with full names.
5. Temperature, Humidity and Rainfall are detected automatically from browser location.
6. Each prediction is automatically saved against the logged-in User ID.
7. My Predictions page shows all predictions saved for that User ID.
8. The original Crop_recommendation.csv is used directly and is not modified.

DATABASE (MySQL)
- Pehle MySQL Server install karke chalu karein.
- config.ini file kholein aur [database] me apna MySQL password (aur zarurat ho
  to port/user) likhein. app.py edit karne ki zarurat nahi hai.
- MySQL ka port 3306 se alag ho (jaise 3307) to bhi app khud sahi port dhoondh leti
  hai. Website ka port 5000 busy ho to app khud agla khaali port le leti hai.
- Database "crop_recommendation" aur tables (users, predictions)
  app start hote hi automatically ban jate hain. (schema.sql optional hai)
- users table me signup ka data (name, email, password hash) store hota hai.
- Passwords plain text me nahi, hash karke store hote hain.

RUN
1. Install Python 3.
2. Double-click run_app.bat.
3. Black window me "Browser me kholein: http://127.0.0.1:XXXX" likha aayega, wahi link kholein
   (normally 5000).
4. Create an account.
5. Allow browser location permission.
6. Temperature, Humidity and Rainfall will be detected automatically.
7. Enter Nitrogen, Phosphorus, Potassium and pH.
8. Click Predict Crop.
9. Open My Predictions to see all predictions saved under your User ID.

WEATHER
- Temperature and Humidity use current Open-Meteo weather data for the detected location.
- Rainfall uses the total rain from the last 365 completed days.
- Internet and browser location permission are required.

IMPORTANT
- Do not edit or replace Crop_recommendation.csv.
- The database file is local to this application folder.
- The weather service is an external online source used only to automatically fill weather values.
